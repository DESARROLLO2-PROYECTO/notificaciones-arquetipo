import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from app.domain import puertos
from app.domain.errores import ColaNoDisponible, NoAutorizado, TipoNotificacionInvalido
from app.domain.notificacion_service import ErrorConcurrenciaAlerta, ServicioNotificaciones

# --- Fakes en memoria (Ports & UnitOfWork) ---


class FakeEquipoRepo:
    def __init__(self) -> None:
        self.equipos: dict[int, puertos.Equipo] = {}

    def crear(self, equipo: puertos.Equipo) -> puertos.Equipo:
        nuevo = replace(equipo, id=len(self.equipos) + 1)
        self.equipos[nuevo.id or 0] = nuevo
        return nuevo

    def obtener(self, id: int) -> puertos.Equipo | None:
        return self.equipos.get(id)


class FakeTipoNotificacionRepo:
    def __init__(self) -> None:
        self.tipos: dict[str, puertos.TipoNotificacion] = {}

    def crear(self, tipo_notificacion: puertos.TipoNotificacion) -> puertos.TipoNotificacion:
        self.tipos[tipo_notificacion.codigo] = tipo_notificacion
        return tipo_notificacion

    def obtener_por_codigo(self, codigo: str) -> puertos.TipoNotificacion | None:
        return self.tipos.get(codigo)


class FakeNotificacionRepo:
    def __init__(self, uow: "FakeUnitOfWork") -> None:
        self._uow = uow

    def crear(self, notificacion: puertos.Notificacion) -> puertos.Notificacion:
        self._uow._pendientes_notificaciones[notificacion.id] = notificacion
        return notificacion

    def obtener(self, id: UUID) -> puertos.Notificacion | None:
        return self._uow.notificaciones_guardadas.get(id)

    def marcar_publicada(self, id: UUID, ahora: datetime) -> None:
        guardada = self._uow.notificaciones_guardadas[id]
        self._uow.notificaciones_guardadas[id] = replace(
            guardada,
            publicada_at=ahora,
            proximo_intento_entrega=ahora + puertos.ESPERA_PRIMERA_ENTREGA,
        )

    def registrar_fallo_publicacion(self, id: UUID, error: str) -> int:
        guardada = self._uow.notificaciones_guardadas[id]
        nueva = replace(
            guardada,
            intentos_publicacion=guardada.intentos_publicacion + 1,
            ultimo_error_publicacion=error,
        )
        self._uow.notificaciones_guardadas[id] = nueva
        return nueva.intentos_publicacion

    def tomar_pendientes_publicacion(
        self, ahora: datetime, limite: int
    ) -> list[puertos.Notificacion]:
        pendientes = [
            n
            for n in self._uow.notificaciones_guardadas.values()
            if n.publicada_at is None
            and n.intentos_publicacion < puertos.MAX_INTENTOS_PUBLICACION
            and n.creada_at <= ahora - puertos.ESPERA_REINTENTO_PUBLICACION
        ]
        return sorted(pendientes, key=lambda n: n.creada_at)[:limite]


class FakeAlertaRepo:
    def __init__(self, uow: "FakeUnitOfWork") -> None:
        self._uow = uow

    def crear(self, alerta: puertos.Alerta) -> puertos.Alerta:
        siguiente_id = len(self._uow.alertas_guardadas) + len(self._uow._pendientes_alertas) + 1
        asignada = replace(alerta, id=siguiente_id)
        self._uow._pendientes_alertas.append(asignada)
        return asignada

    def obtener_activa(self, tipo: str, clave: str, ahora: datetime) -> puertos.Alerta | None:
        for alerta in self._uow.alertas_guardadas:
            if (
                alerta.tipo == tipo
                and alerta.clave == clave
                and alerta.motivo_resolucion is None
                and (alerta.expira_at is None or alerta.expira_at > ahora)
            ):
                return alerta
        return None

    def resolver(self, id: int, motivo: puertos.ResolucionAlerta, ahora: datetime) -> None:
        for i, alerta in enumerate(self._uow.alertas_guardadas):
            if alerta.id == id:
                self._uow.alertas_guardadas[i] = replace(
                    alerta, motivo_resolucion=motivo, resuelta_at=ahora
                )

    def expirar_vencidas(
        self, ahora: datetime, tipo: str | None = None, clave: str | None = None
    ) -> list[puertos.Alerta]:
        cerradas = []
        for i, alerta in enumerate(self._uow.alertas_guardadas):
            if (
                alerta.motivo_resolucion is None
                and alerta.expira_at is not None
                and alerta.expira_at <= ahora
                and tipo in (None, alerta.tipo)
                and clave in (None, alerta.clave)
            ):
                cerrada = replace(
                    alerta, motivo_resolucion=puertos.ResolucionAlerta.EXPIRACION, resuelta_at=ahora
                )
                self._uow.alertas_guardadas[i] = cerrada
                cerradas.append(cerrada)
        return cerradas


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.equipos_fake = FakeEquipoRepo()
        self.tipos_fake = FakeTipoNotificacionRepo()

        # 2. Annotate with the exact Protocol types from puertos.py
        self.equipos: puertos.EquipoRepository = self.equipos_fake
        self.tipos: puertos.TipoNotificacionRepository = self.tipos_fake
        self.notificaciones: puertos.NotificacionRepository = FakeNotificacionRepo(self)
        self.alertas: puertos.AlertaRepository = FakeAlertaRepo(self)

        # Estado confirmado (persiste solo tras commit)
        self.notificaciones_guardadas: dict[UUID, puertos.Notificacion] = {}
        self.alertas_guardadas: list[puertos.Alerta] = []

        # Estado pendiente en transacción
        self._pendientes_notificaciones: dict[UUID, puertos.Notificacion] = {}
        self._pendientes_alertas: list[puertos.Alerta] = []

        self.commits = 0
        self.rollbacks = 0
        self.alerta_concurrente_al_hacer_commit: puertos.Alerta | None = None
        self.fallar_en_commit: Exception | None = None

    def __enter__(self) -> "FakeUnitOfWork":
        self._pendientes_notificaciones.clear()
        self._pendientes_alertas.clear()
        return self

    # 3. Match exact __exit__ type annotations from puertos.UnitOfWork
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.rollback()

    def commit(self) -> None:
        if self.alerta_concurrente_al_hacer_commit is not None:
            ganadora = self.alerta_concurrente_al_hacer_commit
            self.alerta_concurrente_al_hacer_commit = None
            self.alertas_guardadas.append(ganadora)
            raise ErrorConcurrenciaAlerta("Colisión de índice único parcial")

        if self.fallar_en_commit is not None:
            err = self.fallar_en_commit
            self.fallar_en_commit = None
            raise err

        self.notificaciones_guardadas.update(self._pendientes_notificaciones)
        self.alertas_guardadas.extend(self._pendientes_alertas)
        self._pendientes_notificaciones.clear()
        self._pendientes_alertas.clear()
        self.commits += 1

    def rollback(self) -> None:
        self._pendientes_notificaciones.clear()
        self._pendientes_alertas.clear()
        self.rollbacks += 1


class FakePublicador:
    def __init__(self) -> None:
        self.publicados: list[puertos.MensajeNotificacion] = []
        self.caido = False

    def publicar(self, mensaje: puertos.MensajeNotificacion) -> None:
        if self.caido:
            raise ColaNoDisponible("No fue posible publicar en la cola")
        self.publicados.append(mensaje)


# --- Fixtures y helpers ---


@pytest.fixture
def uow() -> FakeUnitOfWork:
    fake = FakeUnitOfWork()
    fake.equipos_fake.equipos[1] = puertos.Equipo(id=1, nombre="inventario", es_admin=False)
    fake.equipos_fake.equipos[2] = puertos.Equipo(id=2, nombre="fabricacion", es_admin=False)

    fake.tipos_fake.tipos["STOCK_BAJO_INSUMO"] = puertos.TipoNotificacion(
        codigo="STOCK_BAJO_INSUMO",
        campo_clave="productoId",
        ttl_alerta_min=60,
        activo=True,
        equipo_emisor_id=1,
        equipo_destino_id=1,
    )
    fake.tipos_fake.tipos["STOCK_BAJO_PRODUCTO"] = puertos.TipoNotificacion(
        codigo="STOCK_BAJO_PRODUCTO",
        campo_clave="productoId",
        ttl_alerta_min=0,
        activo=True,
        equipo_emisor_id=1,
        equipo_destino_id=2,
    )
    fake.tipos_fake.tipos["CONDICION_URGENTE"] = puertos.TipoNotificacion(
        codigo="CONDICION_URGENTE",
        campo_clave="codigoCondicion",
        ttl_alerta_min=60,
        activo=True,
        equipo_emisor_id=2,
        equipo_destino_id=2,
    )
    fake.tipos_fake.tipos["TIPO_INACTIVO"] = puertos.TipoNotificacion(
        codigo="TIPO_INACTIVO",
        campo_clave="productoId",
        ttl_alerta_min=30,
        activo=False,
        equipo_emisor_id=1,
        equipo_destino_id=1,
    )
    return fake


def _datos_stock(**cambios) -> dict:
    base = {
        "tipo": "STOCK_BAJO_INSUMO",
        "evento": "DETECTADA",
        "productoId": "INS-001",
        "nombre": "Acero 304",
        "stockActual": 3,
        "stockMinimo": 10,
    }
    base.update(cambios)
    return base


# --- Tests ---


def test_registrar_notificacion_nueva_crea_notificacion_y_alerta(uow: FakeUnitOfWork, caplog):
    # Arrange
    caplog.set_level(logging.INFO)
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    datos = _datos_stock()

    # Act
    res = servicio.registrar_notificacion(
        "STOCK_BAJO_INSUMO", "DETECTADA", datos, equipo_emisor_id=1
    )

    # Assert
    assert res.duplicada is False
    assert res.tipo == "STOCK_BAJO_INSUMO"
    assert res.destino == "inventario"
    assert res.clave == "INS-001"
    assert res.resultado_log == "REGISTRADA"
    assert uow.commits == 2  # registro + marca de publicación

    # Notificación persistida sin 'mensaje' dentro del payload (Criterio 1)
    notif = uow.notificaciones_guardadas[res.notificacion_id]
    assert notif.tipo == "STOCK_BAJO_INSUMO"
    assert notif.equipo_destino_id == 1
    assert isinstance(notif.payload, dict)
    assert notif.payload == datos
    assert "mensaje" not in notif.payload

    # Alerta activa creada con TTL de 60 minutos
    assert len(uow.alertas_guardadas) == 1
    alerta = uow.alertas_guardadas[0]
    assert alerta.notificacion_id == res.notificacion_id
    assert alerta.clave == "INS-001"
    assert alerta.expira_at is not None
    assert alerta.expira_at > alerta.creada_at

    # Log estructurado (Criterio 8)
    assert (
        "resultado=REGISTRADA tipo=STOCK_BAJO_INSUMO destino=inventario "
        f"clave=INS-001 notificacion_id={res.notificacion_id}" in caplog.text
    )


def test_registrar_con_ttl_cero_deja_expira_at_en_none(uow: FakeUnitOfWork):
    # Arrange
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    datos = _datos_stock(tipo="STOCK_BAJO_PRODUCTO", productoId="CAD-99")

    # Act
    res = servicio.registrar_notificacion(
        "STOCK_BAJO_PRODUCTO", "DETECTADA", datos, equipo_emisor_id=1
    )

    # Assert
    assert res.destino == "fabricacion"
    assert uow.alertas_guardadas[0].expira_at is None


def test_registrar_cuando_ya_existe_alerta_activa_devuelve_id_original(uow: FakeUnitOfWork, caplog):
    # Arrange
    caplog.set_level(logging.INFO)
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    datos = _datos_stock()
    primero = servicio.registrar_notificacion(
        "STOCK_BAJO_INSUMO", "DETECTADA", datos, equipo_emisor_id=1
    )

    # Act (reintento con stock distinto para el mismo tipo y productoId)
    segundo = servicio.registrar_notificacion(
        "STOCK_BAJO_INSUMO", "DETECTADA", _datos_stock(stockActual=1), equipo_emisor_id=1
    )

    # Assert
    assert segundo.duplicada is True
    assert segundo.notificacion_id == primero.notificacion_id
    assert segundo.resultado_log == "ALERTA_YA_ACTIVA"
    assert len(uow.notificaciones_guardadas) == 1
    assert len(uow.alertas_guardadas) == 1
    assert uow.commits == 2  # sin un tercer commit: la duplicada no publica
    assert "resultado=ALERTA_YA_ACTIVA" in caplog.text


def test_registrar_mismo_producto_distinto_tipo_crea_segunda_alerta(uow: FakeUnitOfWork):
    # Arrange
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())

    # Act
    r1 = servicio.registrar_notificacion(
        "STOCK_BAJO_INSUMO", "DETECTADA", _datos_stock(productoId="X-1"), equipo_emisor_id=1
    )
    r2 = servicio.registrar_notificacion(
        "STOCK_BAJO_PRODUCTO",
        "DETECTADA",
        _datos_stock(tipo="STOCK_BAJO_PRODUCTO", productoId="X-1"),
        equipo_emisor_id=1,
    )

    # Assert
    assert r1.notificacion_id != r2.notificacion_id
    assert r2.duplicada is False
    assert len(uow.alertas_guardadas) == 2


def test_registrar_cuando_alerta_anterior_expiro_crea_nueva(uow: FakeUnitOfWork):
    # Arrange
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    pasado = datetime.now(UTC) - timedelta(hours=2)
    alerta_expirada = puertos.Alerta(
        id=1,
        tipo="STOCK_BAJO_INSUMO",
        clave="INS-001",
        notificacion_id=UUID("11111111-1111-1111-1111-111111111111"),
        creada_at=pasado,
        expira_at=pasado + timedelta(minutes=30),
    )
    uow.alertas_guardadas.append(alerta_expirada)

    # Act
    res = servicio.registrar_notificacion(
        "STOCK_BAJO_INSUMO", "DETECTADA", _datos_stock(), equipo_emisor_id=1
    )

    # Assert
    assert res.duplicada is False
    assert res.notificacion_id != alerta_expirada.notificacion_id
    assert len(uow.alertas_guardadas) == 2


@pytest.mark.parametrize("codigo_invalido", ["NO_EXISTE", "TIPO_INACTIVO"])
def test_registrar_tipo_invalido_o_inactivo_lanza_error_y_loggea_rechazo(
    uow: FakeUnitOfWork, caplog, codigo_invalido: str
):
    # Arrange
    caplog.set_level(logging.INFO)
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())

    # Act / Assert
    with pytest.raises(TipoNotificacionInvalido):
        servicio.registrar_notificacion(
            codigo_invalido, "DETECTADA", _datos_stock(tipo=codigo_invalido)
        )

    assert len(uow.notificaciones_guardadas) == 0
    assert len(uow.alertas_guardadas) == 0
    assert (
        f"resultado=RECHAZADA tipo={codigo_invalido} destino=desconocido "
        "clave=INS-001 notificacion_id=None" in caplog.text
    )


@pytest.mark.parametrize("emisor", [2, None])
def test_registrar_con_emisor_distinto_al_del_tipo_lanza_403_y_no_guarda(
    uow: FakeUnitOfWork, caplog, emisor: int | None
):
    # Arrange: STOCK_BAJO_INSUMO lo emite el equipo 1 (inventario)
    caplog.set_level(logging.INFO)
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())

    # Act / Assert
    with pytest.raises(NoAutorizado, match="^Acceso denegado$") as error:
        servicio.registrar_notificacion(
            "STOCK_BAJO_INSUMO", "DETECTADA", _datos_stock(), equipo_emisor_id=emisor
        )

    assert error.value.motivo == "emisor no permitido"
    assert len(uow.notificaciones_guardadas) == 0
    assert len(uow.alertas_guardadas) == 0
    assert uow.commits == 0
    assert (
        "resultado=RECHAZADA tipo=STOCK_BAJO_INSUMO destino=inventario "
        "clave=INS-001 notificacion_id=None" in caplog.text
    )


def test_concurrencia_simultanea_captura_colision_y_devuelve_alerta_ganadora(
    uow: FakeUnitOfWork, caplog
):
    # Arrange (Criterio 6: otro hilo inserta la alerta justo antes de nuestro commit)
    caplog.set_level(logging.INFO)
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    id_ganador = UUID("22222222-2222-2222-2222-222222222222")
    uow.alerta_concurrente_al_hacer_commit = puertos.Alerta(
        id=99,
        tipo="STOCK_BAJO_INSUMO",
        clave="INS-001",
        notificacion_id=id_ganador,
        creada_at=datetime.now(UTC),
    )

    # Act
    res = servicio.registrar_notificacion(
        "STOCK_BAJO_INSUMO", "DETECTADA", _datos_stock(), equipo_emisor_id=1
    )

    # Assert
    assert res.duplicada is True
    assert res.notificacion_id == id_ganador
    assert res.resultado_log == "ALERTA_YA_ACTIVA"
    assert uow.rollbacks == 1
    assert len(uow.notificaciones_guardadas) == 0  # La notificación perdedora no se guardó
    assert "resultado=ALERTA_YA_ACTIVA" in caplog.text


def test_falla_interna_en_commit_hace_rollback_y_no_deja_datos_parciales(uow: FakeUnitOfWork):
    # Arrange (Criterio 7)
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    uow.fallar_en_commit = RuntimeError("Conexión perdida con PostgreSQL")

    # Act / Assert
    with pytest.raises(RuntimeError, match="Conexión perdida"):
        servicio.registrar_notificacion(
            "STOCK_BAJO_INSUMO", "DETECTADA", _datos_stock(), equipo_emisor_id=1
        )

    assert uow.rollbacks == 1
    assert len(uow.notificaciones_guardadas) == 0
    assert len(uow.alertas_guardadas) == 0


def _datos_base() -> dict:
    return {
        "tipo": "STOCK_BAJO_INSUMO",
        "evento": "DETECTADA",
        "productoId": "INS-100",
        "nombre": "Acero",
        "stockActual": 2,
        "stockMinimo": 10,
    }


def _tipo_notif(equipo_destino_id: int | None = 2) -> puertos.TipoNotificacion:
    return puertos.TipoNotificacion(
        codigo="STOCK_BAJO_INSUMO",
        campo_clave="productoId",
        ttl_alerta_min=60,
        activo=True,
        equipo_emisor_id=1,
        equipo_destino_id=equipo_destino_id,
    )


def test_concurrencia_sin_alerta_activa_posterior_relanza_error():
    """Cubre la rama alerta is None tras ErrorConcurrenciaAlerta."""
    uow_1 = MagicMock()
    uow_1.__enter__.return_value = uow_1
    uow_1.tipos.obtener_por_codigo.return_value = _tipo_notif(equipo_destino_id=2)
    uow_1.equipos.obtener.return_value = puertos.Equipo(id=2, nombre="compras", es_admin=False)
    uow_1.alertas.obtener_activa.return_value = None
    uow_1.notificaciones.crear.return_value = puertos.Notificacion(
        id=10,
        tipo="STOCK_BAJO_INSUMO",
        creada_at=None,
        equipo_emisor_id=1,
        equipo_destino_id=2,
        payload=_datos_base(),
    )
    uow_1.commit.side_effect = ErrorConcurrenciaAlerta("colision")

    uow_2 = MagicMock()
    uow_2.__enter__.return_value = uow_2
    uow_2.tipos.obtener_por_codigo.return_value = _tipo_notif()
    # obtener_activa sigue devolviendo None -> cubre línea 53 (raise)
    uow_2.alertas.obtener_activa.return_value = None

    # El reintento único vuelve a chocar: el error sube
    uows = iter([uow_1, uow_2, uow_1])
    servicio = ServicioNotificaciones(lambda: next(uows), FakePublicador())

    with pytest.raises(ErrorConcurrenciaAlerta):
        servicio.registrar_notificacion(
            tipo_codigo="STOCK_BAJO_INSUMO",
            evento="DETECTADA",
            datos=_datos_base(),
            equipo_emisor_id=1,
        )


def test_resolver_destino_sin_equipo_destino_o_equipo_inexistente():
    """Cubre línea 176 (equipo_destino_id is None -> 'desconocido') y rama equipo is None."""
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.tipos.obtener_por_codigo.return_value = _tipo_notif(equipo_destino_id=None)
    uow.alertas.obtener_activa.return_value = None
    uow.notificaciones.crear.return_value = puertos.Notificacion(
        id=11,
        tipo="STOCK_BAJO_INSUMO",
        creada_at=None,
        equipo_emisor_id=1,
        equipo_destino_id=None,
        payload=_datos_base(),
    )

    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    res = servicio.registrar_notificacion(
        tipo_codigo="STOCK_BAJO_INSUMO",
        evento="DETECTADA",
        datos=_datos_base(),
        equipo_emisor_id=1,
    )

    assert res.destino == "desconocido"
    uow.equipos.obtener.assert_not_called()


# --- HU-NOT-02: resolver alertas activas ---


def _registrar(servicio: ServicioNotificaciones, evento: str = "DETECTADA", **cambios):
    datos = _datos_stock(evento=evento, **cambios)
    return servicio.registrar_notificacion("STOCK_BAJO_INSUMO", evento, datos, equipo_emisor_id=1)


@pytest.mark.parametrize("evento", ["REPUESTO", "RESUELTA"])
def test_evento_de_resolucion_cierra_la_alerta_activa(uow: FakeUnitOfWork, caplog, evento):
    caplog.set_level(logging.INFO)
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    original = _registrar(servicio)

    res = _registrar(servicio, evento)

    assert res.resultado_log == "ALERTA_CERRADA"
    assert res.notificacion_id == original.notificacion_id
    alerta = uow.alertas_guardadas[0]
    assert alerta.motivo_resolucion == puertos.ResolucionAlerta.EMISOR
    assert alerta.resuelta_at is not None
    assert len(uow.notificaciones_guardadas) == 1
    assert (
        f"Alerta STOCK_BAJO_INSUMO/INS-001 resuelta por EMISOR "
        f"notificacion_id={original.notificacion_id}" in caplog.text
    )
    assert "resultado=ALERTA_CERRADA tipo=STOCK_BAJO_INSUMO" in caplog.text


def test_evento_de_resolucion_sin_alerta_activa_no_escribe(uow: FakeUnitOfWork):
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())

    res = _registrar(servicio, "REPUESTO")

    assert res.resultado_log == "SIN_ALERTA_ACTIVA"
    assert res.notificacion_id is None
    assert uow.commits == 0
    assert not uow.alertas_guardadas
    assert not uow.notificaciones_guardadas


def test_evento_de_resolucion_de_otro_emisor_es_no_autorizado(uow: FakeUnitOfWork):
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    _registrar(servicio)

    with pytest.raises(NoAutorizado):
        servicio.registrar_notificacion(
            "STOCK_BAJO_INSUMO", "REPUESTO", _datos_stock(evento="REPUESTO"), equipo_emisor_id=2
        )

    assert uow.alertas_guardadas[0].motivo_resolucion is None


def test_detectada_tras_resolver_registra_nueva_notificacion(uow: FakeUnitOfWork):
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    primera = _registrar(servicio)
    _registrar(servicio, "RESUELTA")

    nueva = _registrar(servicio)

    assert nueva.resultado_log == "REGISTRADA"
    assert nueva.notificacion_id != primera.notificacion_id
    assert len(uow.alertas_guardadas) == 2


def test_detectada_con_alerta_vencida_sin_limpiar_registra_nueva(uow: FakeUnitOfWork, caplog):
    caplog.set_level(logging.INFO)
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    primera = _registrar(servicio)
    vieja = uow.alertas_guardadas[0]
    uow.alertas_guardadas[0] = replace(vieja, expira_at=datetime.now(UTC) - timedelta(minutes=1))

    nueva = _registrar(servicio)

    assert nueva.resultado_log == "REGISTRADA"
    assert uow.alertas_guardadas[0].motivo_resolucion == puertos.ResolucionAlerta.EXPIRACION
    assert uow.alertas_guardadas[1].motivo_resolucion is None
    assert (
        f"Alerta STOCK_BAJO_INSUMO/INS-001 resuelta por EXPIRACION "
        f"notificacion_id={primera.notificacion_id}" in caplog.text
    )


def test_ejecutar_ciclo_cierra_vencidas_y_registra_resumen(uow: FakeUnitOfWork, caplog):
    caplog.set_level(logging.INFO)
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    for producto in ("A-1", "A-2", "A-3"):
        _registrar(servicio, productoId=producto)
    pasado = datetime.now(UTC) - timedelta(minutes=1)
    for i in (0, 1):
        uow.alertas_guardadas[i] = replace(uow.alertas_guardadas[i], expira_at=pasado)

    resumen, errores = servicio.ejecutar_ciclo()

    assert resumen == {"alertas": 2, "publicaciones": 0}
    assert errores == []
    assert uow.alertas_guardadas[2].motivo_resolucion is None
    assert "Limpieza de alertas completada: 2 alertas expiradas" in caplog.text
    assert "Alerta STOCK_BAJO_INSUMO/A-1 resuelta por EXPIRACION" in caplog.text


def test_ejecutar_ciclo_continua_si_una_tarea_falla(uow: FakeUnitOfWork, caplog):
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    uow.fallar_en_commit = RuntimeError("falla simulada")

    resumen, errores = servicio.ejecutar_ciclo()

    assert resumen == {"publicaciones": 0}
    assert errores == ["alertas"]
    assert "Falló la tarea del ciclo: alertas" in caplog.text


def test_ejecutar_ciclo_una_tarea_que_falla_no_detiene_a_las_demas(
    uow: FakeUnitOfWork, caplog, monkeypatch
):
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())

    def rota() -> int:
        raise RuntimeError("falla simulada")

    monkeypatch.setattr(servicio, "_tareas_ciclo", lambda: (("rota", rota), ("ok", lambda: 3)))

    assert servicio.ejecutar_ciclo() == ({"ok": 3}, ["rota"])
    assert "Falló la tarea del ciclo: rota" in caplog.text


def test_concurrencia_con_ganador_ya_resuelto_reintenta_una_vez(uow: FakeUnitOfWork):
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    uow.alerta_concurrente_al_hacer_commit = puertos.Alerta(
        tipo="STOCK_BAJO_INSUMO",
        clave="INS-001",
        notificacion_id=UUID(int=1),
        motivo_resolucion=puertos.ResolucionAlerta.EMISOR,
        id=99,
    )

    res = _registrar(servicio)

    assert res.resultado_log == "REGISTRADA"


# --- HU-NOT-03: publicar en el broker ---


def _servicio_con(uow: FakeUnitOfWork) -> tuple[ServicioNotificaciones, FakePublicador]:
    publicador = FakePublicador()
    return ServicioNotificaciones(lambda: uow, publicador), publicador


def _envejecer(uow: FakeUnitOfWork, id: UUID, minutos: int) -> None:
    n = uow.notificaciones_guardadas[id]
    uow.notificaciones_guardadas[id] = replace(
        n, creada_at=datetime.now(UTC) - timedelta(minutes=minutos)
    )


def test_registrar_nueva_publica_y_marca_publicada(uow: FakeUnitOfWork, caplog):
    caplog.set_level(logging.INFO)
    servicio, publicador = _servicio_con(uow)

    res = _registrar(servicio)

    assert publicador.publicados == [
        puertos.MensajeNotificacion(res.notificacion_id, "STOCK_BAJO_INSUMO", "inventario")
    ]
    n = uow.notificaciones_guardadas[res.notificacion_id]
    assert n.publicada_at is not None
    assert n.publicada_at.tzinfo is not None
    assert n.proximo_intento_entrega == n.publicada_at + timedelta(minutes=5)
    assert f"Notificación {res.notificacion_id} publicada correctamente" in caplog.text


def test_registrar_con_cola_caida_queda_pendiente_y_responde_igual(uow: FakeUnitOfWork, caplog):
    caplog.set_level(logging.INFO)
    servicio, publicador = _servicio_con(uow)
    publicador.caido = True

    res = _registrar(servicio)

    n = uow.notificaciones_guardadas[res.notificacion_id]
    assert res.resultado_log == "REGISTRADA"
    assert n.publicada_at is None
    assert n.intentos_publicacion == 1
    assert n.ultimo_error_publicacion == "No fue posible publicar en la cola"
    assert (
        f"Cola no disponible, la notificación {res.notificacion_id} "
        "queda pendiente de publicación" in caplog.text
    )
    assert "publicada correctamente" not in caplog.text


def test_duplicada_y_resolucion_no_publican(uow: FakeUnitOfWork):
    servicio, publicador = _servicio_con(uow)

    _registrar(servicio)
    _registrar(servicio)
    _registrar(servicio, evento="REPUESTO")

    assert len(publicador.publicados) == 1


def test_error_inesperado_al_marcar_no_cambia_el_resultado(uow: FakeUnitOfWork, caplog):
    servicio, _ = _servicio_con(uow)
    original = uow.commit

    def commit() -> None:
        if uow.commits >= 1:
            raise RuntimeError("falla simulada")
        original()

    uow.commit = commit  # type: ignore[method-assign]

    res = _registrar(servicio)

    assert res.resultado_log == "REGISTRADA"
    assert "No se pudo registrar la publicación" in caplog.text


def test_ciclo_reintenta_pendientes_en_orden_de_creacion(uow: FakeUnitOfWork, caplog):
    caplog.set_level(logging.INFO)
    servicio, publicador = _servicio_con(uow)
    publicador.caido = True
    ids = [_registrar(servicio, productoId=f"P-{i}").notificacion_id for i in range(3)]
    for edad, id in zip((5, 10, 1), ids, strict=True):  # la tercera aún no cumple 1 minuto
        _envejecer(uow, id, edad)
    _envejecer(uow, ids[2], 0)
    publicador.caido = False

    resumen, errores = servicio.ejecutar_ciclo()

    assert resumen["publicaciones"] == 2
    assert errores == []
    assert [m.notificacion_id for m in publicador.publicados] == [ids[1], ids[0]]
    assert uow.notificaciones_guardadas[ids[2]].publicada_at is None
    assert f"Notificación {ids[1]} publicada correctamente" in caplog.text


def test_ciclo_no_republica_las_ya_publicadas(uow: FakeUnitOfWork):
    servicio, publicador = _servicio_con(uow)
    res = _registrar(servicio)
    _envejecer(uow, res.notificacion_id, 10)

    assert servicio.ejecutar_ciclo()[0]["publicaciones"] == 0
    assert servicio.ejecutar_ciclo()[0]["publicaciones"] == 0
    assert len(publicador.publicados) == 1


def test_ciclo_con_broker_caido_cuenta_fallos_y_agota_a_los_tres_intentos(
    uow: FakeUnitOfWork, caplog
):
    caplog.set_level(logging.INFO)
    servicio, publicador = _servicio_con(uow)
    publicador.caido = True
    res = _registrar(servicio)
    _envejecer(uow, res.notificacion_id, 10)

    resultados = [servicio.ejecutar_ciclo() for _ in range(3)]
    servicio.ejecutar_ciclo()  # con 3 intentos ya no se toma

    assert all(r == ({"alertas": 0, "publicaciones": 0}, []) for r in resultados)
    assert uow.notificaciones_guardadas[res.notificacion_id].intentos_publicacion == 3
    assert (
        caplog.text.count(
            f"La notificación {res.notificacion_id} no pudo publicarse tras 3 intentos"
        )
        == 1
    )


def _pendientes(servicio: ServicioNotificaciones, uow: FakeUnitOfWork, n: int) -> list[UUID]:
    publicador = servicio._publicador
    assert isinstance(publicador, FakePublicador)
    publicador.caido = True
    ids = [_registrar(servicio, productoId=f"Q-{i}").notificacion_id for i in range(n)]
    for edad, id in zip(range(10 + n, 10, -1), ids, strict=True):
        _envejecer(uow, id, edad)
    publicador.caido = False
    return ids


def test_ciclo_con_broker_caido_se_detiene_en_la_primera_fila(uow: FakeUnitOfWork):
    servicio, publicador = _servicio_con(uow)
    ids = _pendientes(servicio, uow, 3)
    publicador.caido = True

    resumen, _ = servicio.ejecutar_ciclo()

    assert resumen["publicaciones"] == 0
    assert [uow.notificaciones_guardadas[i].intentos_publicacion for i in ids] == [2, 1, 1]


def test_ciclo_error_inesperado_en_una_fila_no_deshace_las_publicadas(uow: FakeUnitOfWork, caplog):
    class PublicadorRoto(FakePublicador):
        def publicar(self, mensaje: puertos.MensajeNotificacion) -> None:
            if len(self.publicados) == 1 and not self.caido:
                self.caido = True  # solo la 2.ª llamada falla
                raise RuntimeError("falla simulada")
            super().publicar(mensaje)

    publicador = PublicadorRoto()
    servicio = ServicioNotificaciones(lambda: uow, publicador)
    ids = _pendientes(servicio, uow, 3)
    publicador.caido = False
    rollbacks = uow.rollbacks

    resumen, errores = servicio.ejecutar_ciclo()

    assert (resumen["publicaciones"], errores) == (1, [])
    assert uow.rollbacks == rollbacks
    n = [uow.notificaciones_guardadas[i] for i in ids]
    assert n[0].publicada_at is not None
    assert (n[1].publicada_at, n[1].intentos_publicacion) == (None, 2)
    assert n[1].ultimo_error_publicacion == "RuntimeError"
    assert "Error inesperado al publicar la notificación" in caplog.text


# --- HU-NOT-05: condición urgente ---


def _registrar_cu(servicio: ServicioNotificaciones, evento: str = "DETECTADA"):
    datos = {
        "tipo": "CONDICION_URGENTE",
        "evento": evento,
        "codigoCondicion": "TEMP-01",
        "descripcion": "Horno caliente",
    }
    return servicio.registrar_notificacion("CONDICION_URGENTE", evento, datos, equipo_emisor_id=2)


def test_condicion_urgente_usa_campo_clave_del_tipo(uow: FakeUnitOfWork):
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())

    res = _registrar_cu(servicio)

    assert res.resultado_log == "REGISTRADA"
    assert res.clave == "TEMP-01"
    assert res.destino == "fabricacion"
    assert uow.alertas_guardadas[0].clave == "TEMP-01"
    assert "mensaje" not in uow.notificaciones_guardadas[res.notificacion_id].payload


def test_condicion_urgente_duplicada_y_resuelta(uow: FakeUnitOfWork):
    servicio = ServicioNotificaciones(lambda: uow, FakePublicador())
    primera = _registrar_cu(servicio)

    duplicada = _registrar_cu(servicio)
    cerrada = _registrar_cu(servicio, "RESUELTA")
    nueva = _registrar_cu(servicio)

    assert duplicada.duplicada is True
    assert duplicada.notificacion_id == primera.notificacion_id
    assert cerrada.resultado_log == "ALERTA_CERRADA"
    assert nueva.resultado_log == "REGISTRADA"
    assert nueva.notificacion_id != primera.notificacion_id


def test_armar_mensaje_condicion_urgente_se_trunca_a_200():
    servicio = ServicioNotificaciones(MagicMock(), FakePublicador())
    datos = {"codigoCondicion": "TEMP-01", "descripcion": "x" * 100}

    mensaje = servicio._armar_mensaje("CONDICION_URGENTE", datos)

    assert mensaje == f"[CONDICION_URGENTE] TEMP-01: {'x' * 100}"
    assert (
        len(servicio._armar_mensaje("CONDICION_URGENTE", {**datos, "descripcion": "x" * 300}))
        == 200
    )

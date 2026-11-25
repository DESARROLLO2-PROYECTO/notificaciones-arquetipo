import pytest
from pydantic import TypeAdapter, ValidationError

from app.api.schemas import (
    CondicionUrgenteRequest,
    CrearNotificacionBody,
    CrearNotificacionRequest,
    EquipoIn,
    EquipoOut,
    EventoNotificacion,
    TipoStockBajo,
)


@pytest.mark.parametrize("clave", ["esAdmin", "es_admin"])
def test_equipo_in_acepta_alias_y_nombre(clave):
    # Arrange / Act
    e = EquipoIn.model_validate({"nombre": "a", clave: True})

    # Assert
    assert e.es_admin is True


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"nombre": "", "esAdmin": False},
        {"nombre": "x" * 51, "esAdmin": False},
        {"nombre": "a", "esAdmin": "si"},
        {"nombre": "a\x00b", "esAdmin": False},
    ],
)
def test_equipo_in_rechaza_invalidos(cuerpo):
    # Act / Assert
    with pytest.raises(ValidationError):
        EquipoIn.model_validate(cuerpo)


def test_equipo_out_serializa_camel():
    # Arrange
    e = EquipoOut(id=1, nombre="a", es_admin=False)

    # Act / Assert
    assert e.model_dump(by_alias=True) == {"id": 1, "nombre": "a", "esAdmin": False}


def _payload_valido(**cambios) -> dict:
    base = {
        "tipo": "STOCK_BAJO_INSUMO",
        "productoId": "INS-001",
        "nombre": "Acero inoxidable 304",
        "stockActual": 5,
        "stockMinimo": 10,
    }
    base.update(cambios)
    return base


def test_notificacion_request_valido_defaults_y_normalizacion():
    # Arrange
    cuerpo = _payload_valido(productoId=12345)

    # Act
    req = CrearNotificacionRequest.model_validate(cuerpo)

    # Assert
    assert req.tipo == TipoStockBajo.STOCK_BAJO_INSUMO
    assert req.evento == EventoNotificacion.DETECTADA
    assert req.productoId == "12345"


@pytest.mark.parametrize(
    "cambios",
    [
        {"tipo": "STOCK_BAJO_PRODUCTO"},
        {"evento": "DETECTADA"},
        {"evento": "REPUESTO"},
        {"evento": "RESUELTA"},
        {"productoId": "A"},
        {"productoId": "A" * 50},
        {"productoId": "PROD-2026-abc"},
        {"productoId": 0},
        {"nombre": "X"},
        {"nombre": "X" * 100},
        {"stockActual": 0, "stockMinimo": 0},
        {"stockActual": 1_000_000, "stockMinimo": 1_000_000},
        # Criterio 5: stockActual >= stockMinimo debe aceptarse si la forma es válida
        {"stockActual": 50, "stockMinimo": 10},
        {"stockActual": 10, "stockMinimo": 10},
    ],
)
def test_notificacion_request_acepta_casos_validos_y_limites(cambios):
    # Arrange
    cuerpo = _payload_valido(**cambios)

    # Act
    req = CrearNotificacionRequest.model_validate(cuerpo)

    # Assert
    assert req is not None


@pytest.mark.parametrize(
    "campo_a_eliminar",
    ["tipo", "productoId", "nombre", "stockActual", "stockMinimo"],
)
def test_notificacion_request_rechaza_campos_obligatorios_faltantes(campo_a_eliminar):
    # Arrange
    cuerpo = _payload_valido()
    del cuerpo[campo_a_eliminar]

    # Act / Assert
    with pytest.raises(ValidationError):
        CrearNotificacionRequest.model_validate(cuerpo)


@pytest.mark.parametrize(
    "cambios",
    [
        # productoId inválido
        {"productoId": ""},
        {"productoId": " "},
        {"productoId": "INS 001"},
        {"productoId": "INS_001"},
        {"productoId": "INS.001"},
        {"productoId": "A" * 51},
        {"productoId": True},
        {"productoId": 12.5},
        {"productoId": None},
        # nombre inválido
        {"nombre": ""},
        {"nombre": "   "},
        {"nombre": "x" * 101},
        {"nombre": 123},
        # stockActual inválido
        {"stockActual": -1},
        {"stockActual": 1_000_001},
        {"stockActual": 5.5},
        {"stockActual": "5"},
        {"stockActual": True},
        # stockMinimo inválido
        {"stockMinimo": -1},
        {"stockMinimo": 1_000_001},
        {"stockMinimo": 10.1},
        {"stockMinimo": "10"},
        {"stockMinimo": False},
        # evento inválido
        {"evento": "OTRO"},
        {"evento": "detectada"},
        {"evento": ""},
    ],
)
def test_notificacion_request_rechaza_formatos_y_rangos_invalidos(cambios):
    # Arrange
    cuerpo = _payload_valido(**cambios)

    # Act / Assert
    with pytest.raises(ValidationError):
        CrearNotificacionRequest.model_validate(cuerpo)


@pytest.mark.parametrize("valor_bool", [True, False])
def test_validar_producto_id_rechaza_bool_directo(valor_bool):
    with pytest.raises(ValueError, match="productoId debe ser entero o texto alfanumérico"):
        CrearNotificacionRequest.validar_producto_id(valor_bool)


# --- HU-NOT-05: condición urgente ---


def _cu(**cambios) -> dict:
    base = {
        "tipo": "CONDICION_URGENTE",
        "codigoCondicion": "TEMP-01",
        "descripcion": "Horno caliente",
    }
    base.update(cambios)
    return base


def test_condicion_urgente_valida_con_evento_por_defecto():
    req = TypeAdapter(CrearNotificacionBody).validate_python(_cu())

    assert isinstance(req, CondicionUrgenteRequest)
    assert req.evento == EventoNotificacion.DETECTADA


def test_union_sigue_aceptando_stock():
    req = TypeAdapter(CrearNotificacionBody).validate_python(_payload_valido())

    assert isinstance(req, CrearNotificacionRequest)


@pytest.mark.parametrize(
    "cambios",
    [
        {"codigoCondicion": ""},
        {"codigoCondicion": "A" * 31},
        {"codigoCondicion": "TEMP 01"},
        {"codigoCondicion": "TEMP_01"},
        {"codigoCondicion": 5},
        {"descripcion": ""},
        {"descripcion": "   "},
        {"descripcion": "x" * 101},
        {"evento": "OTRO"},
        {"extra": 1},
    ],
)
def test_condicion_urgente_rechaza_invalidos(cambios):
    with pytest.raises(ValidationError):
        TypeAdapter(CrearNotificacionBody).validate_python(_cu(**cambios))


@pytest.mark.parametrize("campo", ["codigoCondicion", "descripcion"])
def test_condicion_urgente_rechaza_faltantes(campo):
    cuerpo = _cu()
    del cuerpo[campo]

    with pytest.raises(ValidationError):
        TypeAdapter(CrearNotificacionBody).validate_python(cuerpo)


def test_union_rechaza_tipo_desconocido():
    with pytest.raises(ValidationError):
        TypeAdapter(CrearNotificacionBody).validate_python(_cu(tipo="OTRO"))

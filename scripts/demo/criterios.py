"""Demo por criterios de aceptación: recorre una historia criterio por criterio.

    python -m scripts.demo.criterios --hu 11        # HU-NOT-11: generar y desactivar API Keys
    python -m scripts.demo.criterios --hu 01        # HU-NOT-01: reportar stock bajo
    python -m scripts.demo.criterios --hu 11 --solo 3,4   # solo algunos criterios

Cada criterio muestra su texto del backlog, el comando de ejemplo (curl o consola), la respuesta
real del servicio y, con el `docker compose` local, la evidencia en la base de datos o en los
registros. Termina con un resumen de ✓ y ✗.
"""

import base64
import hashlib
import json
import re
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from scripts.demo.configuracion import (
    Configuracion,
    configuracion_de,
    crear_parser,
    preparar_llaves,
)
from scripts.demo.entorno import DockerLocal, Entorno
from scripts.demo.equipos_falsos import ClienteApi
from scripts.demo.salida import Respuesta, Salida

CORRECTO, COMPROBACION_FALLIDA, SIN_EJECUTAR = 0, 1, 2
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_LLAVE = re.compile(r"API Key \(se muestra una sola vez\): (\S+)")
_ID = re.compile(r"^ID: (\d+)", re.MULTILINE)
_MENSAJE_422 = "Los datos enviados no cumplen las reglas establecidas"


@dataclass
class Contexto:
    config: Configuracion
    salida: Salida
    api: ClienteApi
    entorno: Entorno
    solo: set[int]
    conservar: bool = False
    parar_bd: bool = True
    hilos: int = 10

    def toca(self, criterio: int) -> bool:
        return not self.solo or criterio in self.solo

    def sql(self, consulta: str) -> list[list[str]]:
        """Evidencia de la base de datos; vacía si no hay acceso (la API está en otra máquina)."""
        return self.entorno.sql(consulta) if self.entorno.disponible else []

    def curl(
        self, metodo: str, ruta: str, cuerpo: dict[str, Any] | None = None, llave: str | None = None
    ) -> None:
        """Muestra el curl equivalente, con variables para que se pueda copiar y pegar."""
        partes = [f'curl -X {metodo} "$DEMO_URL{ruta}"']
        if llave:
            partes.append(f'-H "X-API-Key: ${llave}"')
        if cuerpo is not None:
            partes.append('-H "Content-Type: application/json"')
            partes.append(f"-d '{json.dumps(cuerpo, ensure_ascii=False)}'")
        self.salida.comando(" \\\n  ".join(partes), "curl equivalente")

    def http(
        self,
        quien: str,
        metodo: str,
        ruta: str,
        cuerpo: dict[str, Any] | None,
        llave: str | None,
        variable: str | None,
        esperado: int,
        significado: str,
    ) -> tuple[Respuesta, bool]:
        self.curl(metodo, ruta, cuerpo, variable)
        self.salida.solicitud(quien, metodo, ruta, cuerpo)
        r = self.api.enviar(metodo, ruta, llave, cuerpo)
        return r, self.salida.respuesta(r, esperado, significado)


def _id(r: Respuesta) -> str | None:
    return r.cuerpo.get("id") if isinstance(r.cuerpo, dict) else None


def _mensaje(r: Respuesta) -> str | None:
    return r.cuerpo.get("mensaje") if isinstance(r.cuerpo, dict) else None


def _campos(r: Respuesta) -> list[str]:
    errores = r.cuerpo.get("errores", []) if isinstance(r.cuerpo, dict) else []
    return [str(e.get("campo")) for e in errores]


def _consola(c: Contexto, *args: str) -> tuple[int, str, str]:
    """Ejecuta una herramienta de consola mostrando el comando y su salida real."""
    c.salida.comando(c.entorno.texto_cli(*args), "Comando")
    codigo, salida, errores = c.entorno.cli(*args)
    for linea in (salida + errores).strip().splitlines():
        c.salida.linea(f"       {linea}")
    return codigo, salida, errores


# ---------------------------------------------------------------------------------------------
# HU-NOT-11
# ---------------------------------------------------------------------------------------------
def _activas(c: Contexto) -> dict[str, int]:
    filas = c.sql(
        "select e.nombre, count(k.id) filter (where k.activa) from equipos e "
        "left join api_keys k on k.equipo_id = e.id "
        "where e.nombre in ('inventario','fabricacion','notificaciones') group by e.nombre"
    )
    return {nombre: int(n) for nombre, n in filas}


def _crear(c: Contexto, rol: str, creadas: list[tuple[int, str, str]]) -> tuple[int, str, str]:
    codigo, salida, errores = _consola(c, "scripts.crear_api_key", "--rol", rol)
    id_, llave = _ID.search(salida), _LLAVE.search(salida)
    if codigo == 0 and id_ and llave:
        creadas.append((int(id_.group(1)), rol, llave.group(1)))
    return codigo, salida, errores


def hu_11(c: Contexto) -> None:
    s = c.salida
    s.titulo("HU-NOT-11 · Generar y desactivar API Keys")
    s.nota("Como administrador de Notificaciones requiero generar una API Key para un servicio,")
    s.nota("para que ese servicio pueda autenticarse con permisos y un rol definido.")
    if not c.entorno.disponible:
        s.linea("   ✗ Esta historia se muestra con las herramientas de consola del servicio y")
        s.linea("     necesita el docker compose local corriendo (docker compose up --build -d).")
        s.registrar("HU-NOT-11", "requiere el docker compose local", False)
        return
    activas = _activas(c)
    libres = [r for r, n in sorted(activas.items(), key=lambda x: x[1]) if n < 2]
    if not libres:
        s.linea("   ✗ Los tres roles ya tienen dos llaves activas; desactive una primero con:")
        s.linea("     docker compose exec -T api python -m scripts.desactivar_api_key --id <ID>")
        s.registrar("HU-NOT-11", "hay un rol con cupo libre", False)
        return
    rol = "inventario" if "inventario" in libres else libres[0]
    creadas: list[tuple[int, str, str]] = []
    s.nota(f"Llaves activas por rol: {', '.join(f'{r}={n}' for r, n in sorted(activas.items()))}.")
    s.nota(f"Se usa el rol «{rol}». Las llaves que cree la demo se desactivan al final.")
    s.comando(c.entorno.texto_cli("scripts.listar_api_keys"), "Para ver las llaves (sin su valor)")
    _consola(c, "scripts.listar_api_keys")

    try:
        _hu11_criterios(c, rol, creadas)
    finally:
        if not c.conservar:
            for id_, _, _ in creadas:
                c.entorno.cli("scripts.desactivar_api_key", "--id", str(id_))
            if creadas:
                s.nota(f"Limpieza: se desactivaron las {len(creadas)} llaves creadas por la demo.")


def _hu11_criterios(c: Contexto, rol: str, creadas: list[tuple[int, str, str]]) -> None:
    s = c.salida
    if c.toca(1):
        s.criterio(
            1,
            "Dado que el administrador ejecuta el script de generación indicando el rol del "
            "servicio, cuando el script termina, entonces genera una API Key aleatoria de al "
            "menos 32 bytes, la muestra una sola vez en la consola junto con su identificador, "
            "y guarda únicamente su hash (SHA-256), el rol, la fecha de creación (UTC ISO 8601) "
            "y el estado activa.",
        )
        codigo, salida, _ = _crear(c, rol, creadas)
        s.comprobar(
            "Criterio 1",
            "el script termina bien y muestra ID y llave",
            codigo == 0 and bool(creadas),
        )
        if creadas:
            id_, _, llave = creadas[-1]
            largo = len(base64.urlsafe_b64decode(llave + "=" * (-len(llave) % 4)))
            s.comprobar(
                "Criterio 1", f"la llave tiene {largo} bytes aleatorios (mínimo 32)", largo >= 32
            )
            fila = c.sql(
                "select k.id, e.nombre, k.hash, k.prefijo, k.activa, k.creada_at from api_keys k "
                f"join equipos e on e.id = k.equipo_id where k.id = {id_}"
            )
            if fila:
                _, rol_bd, hash_bd, prefijo, activa, creada = fila[0]
                s.evidencia("En la base de datos (tabla api_keys):", [
                    f"rol={rol_bd}  activa={activa}  creada_at={creada}",
                    f"hash (SHA-256) = {hash_bd}",
                    f"prefijo = {prefijo}",
                ])  # fmt: skip
                s.comprobar("Criterio 1", "lo guardado es el SHA-256 de la llave, no la llave",
                            hash_bd == hashlib.sha256(llave.encode()).hexdigest() and llave not in "".join(fila[0]))  # fmt: skip
                s.comprobar(
                    "Criterio 1",
                    "queda activa y con el rol pedido",
                    activa == "t" and rol_bd == rol,
                )
        s.pausa()

    if c.toca(2):
        s.criterio(
            2,
            "Dado que el rol indicado no es inventario, fabricacion ni notificaciones, cuando el "
            "administrador ejecuta el script, entonces no genera ninguna llave y muestra el "
            'mensaje "Rol no válido".',
        )
        antes = c.sql("select count(*) from api_keys")
        codigo, salida, errores = _consola(c, "scripts.crear_api_key", "--rol", "marciano")
        despues = c.sql("select count(*) from api_keys")
        s.comprobar("Criterio 2", 'muestra "Rol no válido" y termina con error', codigo != 0 and "Rol no válido" in salida + errores)  # fmt: skip
        s.comprobar("Criterio 2", f"no se creó ninguna llave (filas: {antes[0][0]} → {despues[0][0]})", antes == despues)  # fmt: skip
        s.pausa()

    if c.toca(3):
        s.criterio(
            3,
            "Dado que ya existen dos API Keys activas para el rol indicado, cuando el "
            "administrador ejecuta el script de generación, entonces no genera una nueva y "
            'muestra el mensaje "Ya existen dos llaves activas para este rol" (permite rotar '
            "llaves sin cortar el servicio).",
        )
        while _activas(c).get(rol, 0) < 2:
            if _crear(c, rol, creadas)[0] != 0:
                break
        s.nota(f"El rol «{rol}» ya tiene dos llaves activas. Se intenta crear una tercera:")
        codigo, salida, errores = _consola(c, "scripts.crear_api_key", "--rol", rol)
        s.comprobar("Criterio 3", 'muestra "Ya existen dos llaves activas para este rol"', codigo != 0 and "Ya existen dos llaves activas para este rol" in salida + errores)  # fmt: skip
        s.comprobar("Criterio 3", "el rol sigue con exactamente dos llaves activas", _activas(c).get(rol) == 2)  # fmt: skip
        s.pausa()

    if c.toca(4):
        s.criterio(
            4,
            "Dado que el administrador necesita retirar una llave, cuando ejecuta el script de "
            "desactivación indicando su identificador, entonces la llave pasa a estado inactiva "
            "y deja de ser aceptada por la API de Notificaciones.",
        )
        if not creadas:
            _crear(c, rol, creadas)
        id_, _, llave = creadas[0]
        s.nota("Primero la llave funciona: se usa para consultar un equipo.")
        s.nota(
            "En los curl de este criterio, $LLAVE_NUEVA es la llave que mostró el script de generación."
        )
        _, ok = c.http("Servicio", "GET", "/equipos/1", None, llave, "LLAVE_NUEVA", 200, "La API acepta la llave activa.")  # fmt: skip
        s.comprobar("Criterio 4", "con la llave activa la API responde 200", ok)
        codigo, salida, _ = _consola(c, "scripts.desactivar_api_key", "--id", str(id_))
        s.comprobar("Criterio 4", "el script informa que la llave quedó desactivada", codigo == 0 and "desactivada" in salida)  # fmt: skip
        _, ok = c.http("Servicio", "GET", "/equipos/1", None, llave, "LLAVE_NUEVA", 401, "La misma llave ya no entra.")  # fmt: skip
        s.comprobar("Criterio 4", "con la llave desactivada la API responde 401", ok)
        fila = c.sql(f"select activa from api_keys where id = {id_}")
        s.evidencia("En la base de datos el registro se conserva:", [f"id={id_}  activa={fila[0][0] if fila else '?'}"])  # fmt: skip
        s.comprobar("Criterio 4", "el registro se conserva, solo cambia su estado", bool(fila) and fila[0][0] == "f")  # fmt: skip
        s.nota(
            "Con el cupo liberado se puede rotar: crear la llave nueva antes de entregar la vieja."
        )
        codigo, _, _ = _crear(c, rol, creadas)
        s.comprobar("Criterio 4", "al liberar un cupo se puede generar otra llave", codigo == 0)
        s.pausa()

    if c.toca(5):
        s.criterio(
            5,
            "Dado que se genera o desactiva una llave, cuando termina la operación, entonces el "
            "valor completo de la llave no queda en ningún log ni en la base de datos.",
        )
        if not creadas:
            _crear(c, rol, creadas)
        registros = c.entorno.registros()
        en_logs = sum(llave in registros for _, _, llave in creadas)
        en_bd = 0
        for _, _, llave in creadas:
            filas = c.sql(f"select count(*) from api_keys k where k::text like '%{llave}%'")
            en_bd += int(filas[0][0]) if filas else 0
        s.evidencia("Búsqueda de las llaves completas creadas en esta demo:", [
            f"en los registros del servicio api (docker compose logs): {en_logs} coincidencias",
            f"en la tabla api_keys (todas las columnas): {en_bd} coincidencias",
        ])  # fmt: skip
        s.comprobar("Criterio 5", f"ninguna de las {len(creadas)} llaves aparece en los registros", en_logs == 0)  # fmt: skip
        s.comprobar("Criterio 5", "ninguna aparece en la base de datos", en_bd == 0)
        s.pausa()

    if c.toca(6):
        s.criterio(
            6,
            "Dado que se despliega el servicio por primera vez, cuando el administrador genera "
            "la primera llave con rol notificaciones, entonces esa llave puede usarse como "
            "secreto del proceso programado que ejecuta el ciclo y para administrar el servicio.",
        )
        admin = next((k for _, r, k in creadas if r == "notificaciones"), None)
        if admin is None and _activas(c).get("notificaciones", 0) < 2:
            codigo, _, _ = _crear(c, "notificaciones", creadas)
            admin = creadas[-1][2] if codigo == 0 else None
        variable_admin = "LLAVE_NUEVA"
        if admin is None:
            admin = c.config.llaves.get("notificaciones") or None
            variable_admin = "DEMO_LLAVE_ADMIN"
        if admin is None:
            s.nota("No hay una llave de administración disponible para esta escena.")
            s.comprobar("Criterio 6", "hay una llave de rol notificaciones", False)
        else:
            if variable_admin == "LLAVE_NUEVA":
                s.nota(
                    "Aquí $LLAVE_NUEVA es la llave de rol notificaciones que se acaba de generar."
                )
            _, ok = c.http("Administración", "POST", "/notificaciones/ciclo", None, admin, variable_admin, 200, "La llave administrativa ejecuta el ciclo (lo que hará el planificador).")  # fmt: skip
            s.comprobar("Criterio 6", "la llave notificaciones ejecuta el ciclo (200)", ok)
            otra = c.config.llaves.get("inventario")
            if otra:
                _, ok = c.http("Inventario", "POST", "/notificaciones/ciclo", None, otra, "DEMO_LLAVE_INVENTARIO", 403, "Una llave de otro rol no puede administrar.")  # fmt: skip
                s.comprobar("Criterio 6", "una llave de otro rol recibe 403", ok)
        s.pausa()


# ---------------------------------------------------------------------------------------------
# HU-NOT-01
# ---------------------------------------------------------------------------------------------
def _stock(producto: str, **cambios: Any) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {
        "tipo": "STOCK_BAJO_INSUMO",
        "evento": "DETECTADA",
        "productoId": producto,
        "nombre": "Acero inoxidable 304",
        "stockActual": 4,
        "stockMinimo": 10,
    }
    cuerpo.update(cambios)
    return {k: v for k, v in cuerpo.items() if v is not None}


def _filas_notificacion(c: Contexto, id_: str) -> list[list[str]]:
    return c.sql(
        "select n.id, n.tipo, d.nombre, n.creada_at, n.payload from notificaciones n "
        f"join equipos d on d.id = n.equipo_destino_id where n.id = '{id_}'"
    )


def hu_01(c: Contexto) -> None:
    s = c.salida
    s.titulo("HU-NOT-01 · Reportar un nivel de stock bajo")
    s.nota("Como API de Inventario requiero reportar un nivel de stock bajo, para que el equipo")
    s.nota(
        "destino (Inventario o Fabricación) se entere oportunamente de la necesidad de reabastecer."
    )
    llave = c.config.llaves["inventario"]
    var = "DEMO_LLAVE_INVENTARIO"
    corrida = f"{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
    producto = f"HU01-ACERO-{corrida}"
    if not c.entorno.disponible:
        s.nota(
            "Sin el docker compose local no hay acceso a la base de datos: se omite la evidencia en BD."
        )  # noqa: E501
    ctx: dict[str, Any] = {}

    if c.toca(1) or c.toca(2) or c.toca(3):
        pass
    if c.toca(1):
        s.criterio(
            1,
            "Dado que la API de Inventario detecta que la existencia de un artículo quedó por "
            "debajo de su mínimo, cuando envía POST /notificaciones en JSON con una API Key "
            "válida de rol inventario (tipo, evento, productoId, nombre, stockActual y "
            "stockMinimo) y no existe una alerta activa para ese tipo y productoId, entonces la "
            "API registra una notificación con id (UUID de 36 caracteres), tipo, destino "
            "(inventario para STOCK_BAJO_INSUMO, fabricacion para STOCK_BAJO_PRODUCTO), mensaje "
            "(máximo 200 caracteres, calculado, no se guarda), fecha de registro (UTC ISO 8601) "
            "y los datos recibidos, y deja activa la alerta.",
        )
        cuerpo = _stock(producto)
        r, ok = c.http("Inventario", "POST", "/notificaciones", cuerpo, llave, var, 201, "Se registró la notificación y quedó activa la alerta.")  # fmt: skip
        ctx["id"], ctx["r1"] = _id(r), r
        s.comprobar("Criterio 1", "el id es un UUID de 36 caracteres", bool(ctx["id"]) and bool(_UUID.match(str(ctx["id"]))))  # fmt: skip
        fila = _filas_notificacion(c, str(ctx["id"])) if ctx["id"] else None
        if fila:
            _, tipo, destino, creada, payload = fila[0]
            datos = json.loads(payload)
            alerta = c.sql(f"select clave, cerrada_at is null, expira_at > now() from alertas where notificacion_id = '{ctx['id']}'")  # fmt: skip
            s.evidencia("En la base de datos:", [
                f"notificaciones: tipo={tipo}  destino={destino}  creada_at={creada}",
                f"payload (datos recibidos) = {json.dumps(datos, ensure_ascii=False)}",
                f"alertas: clave={alerta[0][0] if alerta else '?'}  activa={alerta[0][1] if alerta else '?'}",
            ])  # fmt: skip
            s.comprobar(
                "Criterio 1", "destino inventario para STOCK_BAJO_INSUMO", destino == "inventario"
            )
            s.comprobar("Criterio 1", "guarda los datos recibidos y no guarda el mensaje", datos == cuerpo | {} and "mensaje" not in datos)  # fmt: skip
            s.comprobar("Criterio 1", "la alerta del artículo quedó activa", bool(alerta) and alerta[0][1] == "t")  # fmt: skip
        s.nota("Con STOCK_BAJO_PRODUCTO (cadenas y cuchillas) el destino es Fabricación:")
        otro = _stock(f"HU01-CADENA-{corrida}", tipo="STOCK_BAJO_PRODUCTO", nombre="Cadena 3/8")
        r, ok = c.http("Inventario", "POST", "/notificaciones", otro, llave, var, 201, "Otro tipo, otro destino.")  # fmt: skip
        fila = _filas_notificacion(c, str(_id(r))) if _id(r) else None
        if fila:
            s.comprobar("Criterio 1", "destino fabricacion para STOCK_BAJO_PRODUCTO", fila[0][2] == "fabricacion")  # fmt: skip
        s.pausa()

    if c.toca(2):
        s.criterio(
            2,
            "Dado que la notificación de stock bajo fue registrada, cuando la API termina el "
            'registro, entonces responde HTTP 201 con el id y el mensaje "Notificación '
            'registrada correctamente".',
        )
        if "r1" not in ctx:
            ctx["r1"] = c.api.enviar("POST", "/notificaciones", llave, _stock(f"HU01-C2-{corrida}"))
            c.curl("POST", "/notificaciones", _stock(f"HU01-C2-{corrida}"), var)
        r = ctx["r1"]
        s.linea(
            f"   La respuesta del criterio 1 fue: {r.estado}  {json.dumps(r.cuerpo, ensure_ascii=False)}"
        )
        s.comprobar("Criterio 2", "responde 201", r.estado == 201)
        s.comprobar("Criterio 2", 'el mensaje es "Notificación registrada correctamente"', _mensaje(r) == "Notificación registrada correctamente")  # fmt: skip
        s.pausa()

    if c.toca(3):
        s.criterio(
            3,
            "Dado que ya existe una alerta activa para el mismo tipo y productoId, cuando la API "
            "de Inventario envía de nuevo el evento DETECTADA (por un reintento o porque la "
            "condición persiste), entonces la API no registra una nueva notificación y responde "
            "HTTP 200 con el id de la notificación existente, duplicada en verdadero y el "
            'mensaje "Ya existe una alerta activa para este artículo".',
        )
        if "id" not in ctx:
            r0 = c.api.enviar("POST", "/notificaciones", llave, _stock(producto))
            ctx["id"] = _id(r0)
        r, ok = c.http("Inventario", "POST", "/notificaciones", _stock(producto), llave, var, 200, "Es el mismo artículo con la alerta activa: no se duplica.")  # fmt: skip
        b = r.cuerpo if isinstance(r.cuerpo, dict) else {}
        s.comprobar(
            "Criterio 3", "devuelve el id de la notificación existente", _id(r) == ctx["id"]
        )
        s.comprobar("Criterio 3", "duplicada en verdadero", b.get("duplicada") is True)
        s.comprobar("Criterio 3", 'mensaje "Ya existe una alerta activa para este artículo"', _mensaje(r) == "Ya existe una alerta activa para este artículo")  # fmt: skip
        n = c.sql(
            f"select count(*) from notificaciones where payload->>'productoId' = '{producto}'"
        )
        if n:
            s.evidencia("En la base de datos:", [f"notificaciones de {producto}: {n[0][0]}"])
            s.comprobar(
                "Criterio 3", "sigue habiendo una sola notificación del artículo", n[0][0] == "1"
            )
        s.pausa()

    if c.toca(4):
        _hu01_criterio4(c, llave, var, corrida)
    if c.toca(5):
        s.criterio(
            5,
            "Dado que la API de Inventario envía un evento DETECTADA con la forma correcta, "
            "cuando stockActual no es menor que stockMinimo, entonces la API igualmente procesa "
            "el evento: no verifica si el reporte de Inventario es correcto, solo valida su forma.",
        )
        cuerpo = _stock(f"HU01-C5-{corrida}", stockActual=50, stockMinimo=10)
        s.nota("Aquí stockActual (50) NO es menor que stockMinimo (10).")
        r, ok = c.http("Inventario", "POST", "/notificaciones", cuerpo, llave, var, 201, "El módulo no juzga el reporte: solo valida su forma.")  # fmt: skip
        s.comprobar("Criterio 5", "lo procesa igual (201)", ok)
        s.pausa()
    if c.toca(6):
        _hu01_criterio6(c, llave, var, corrida)
    if c.toca(7):
        _hu01_criterio7(c, llave, var, corrida)
    if c.toca(8):
        _hu01_criterio8(c, llave, var, corrida, ctx.get("id"))


def _hu01_criterio4(c: Contexto, llave: str, var: str, corrida: str) -> None:
    s = c.salida
    s.criterio(
        4,
        "Dado que los datos no cumplen la forma establecida (falta un campo; tipo o formato "
        "incorrecto; productoId con caracteres no permitidos, espacios o más de 50; nombre vacío "
        "o de más de 100; números con decimales, negativos o mayores a 1.000.000; tipo fuera del "
        "catálogo; evento inválido), cuando la API los valida, entonces no registra la "
        f'notificación y responde HTTP 422 con el mensaje "{_MENSAJE_422}" y la lista de campos '
        "con su error.",
    )
    p = f"HU01-C4-{corrida}"
    casos: list[tuple[str, dict[str, Any]]] = [
        ("falta tipo", _stock(p, tipo=None)),
        ("falta productoId", _stock(p, productoId=None)),
        ("falta nombre", _stock(p, nombre=None)),
        ("falta stockActual", _stock(p, stockActual=None)),
        ("falta stockMinimo", _stock(p, stockMinimo=None)),
        ("stockActual no es número", _stock(p, stockActual="diez")),
        ("productoId con espacios", _stock("con espacios")),
        ("productoId con caracteres no permitidos", _stock("ART/001")),
        ("productoId de más de 50 caracteres", _stock("A" * 51)),
        ("nombre vacío", _stock(p, nombre="")),
        ("nombre de más de 100 caracteres", _stock(p, nombre="N" * 101)),
        ("stockActual con decimales", _stock(p, stockActual=4.5)),
        ("stockMinimo negativo", _stock(p, stockMinimo=-1)),
        ("stockActual mayor a 1.000.000", _stock(p, stockActual=1_000_001)),
        ("tipo fuera del catálogo", _stock(p, tipo="NO_EXISTE")),
        ("evento distinto de DETECTADA, REPUESTO o RESUELTA", _stock(p, evento="CANCELADA")),
    ]
    antes = c.sql("select count(*) from notificaciones")
    c.curl("POST", "/notificaciones", casos[6][1], var)
    s.nota(
        "Se envían 16 solicitudes inválidas; el curl de arriba es la de «productoId con espacios»."
    )
    todas = True
    for descripcion, cuerpo in casos:
        r = c.api.enviar("POST", "/notificaciones", llave, cuerpo)
        correcto = r.estado == 422 and _mensaje(r) == _MENSAJE_422 and bool(_campos(r))
        todas &= correcto
        marca = "✓" if correcto else "✗"
        s.linea(f"   {marca} {r.estado}  {descripcion:<52} campos con error: {', '.join(_campos(r)) or '-'}")  # fmt: skip
    s.comprobar("Criterio 4", f"las {len(casos)} solicitudes inválidas se rechazan con 422, el mensaje y la lista de campos", todas)  # fmt: skip
    despues = c.sql("select count(*) from notificaciones")
    if antes and despues:
        s.evidencia(
            "En la base de datos:",
            [f"notificaciones antes: {antes[0][0]}  después: {despues[0][0]}"],
        )
        s.comprobar("Criterio 4", "no se registró ninguna notificación", antes == despues)
    s.pausa()


def _hu01_criterio6(c: Contexto, llave: str, var: str, corrida: str) -> None:
    s = c.salida
    s.criterio(
        6,
        "Dado que llegan al mismo tiempo dos solicitudes DETECTADA para el mismo tipo y "
        "productoId sin alerta activa, cuando la API las procesa, entonces registra una sola "
        "notificación y responde a la otra con HTTP 200 y el id de la notificación existente.",
    )
    producto = f"HU01-C6-{corrida}"
    cuerpo = _stock(producto)
    c.curl("POST", "/notificaciones", cuerpo, var)
    s.nota(
        f"Se envían {c.hilos} solicitudes idénticas a la vez (varios hilos), con un artículo nuevo."
    )
    with ThreadPoolExecutor(max_workers=c.hilos) as pool:
        respuestas = list(pool.map(lambda _: c.api.enviar("POST", "/notificaciones", llave, cuerpo), range(c.hilos)))  # fmt: skip
    codigos: dict[int, int] = {}
    for r in respuestas:
        codigos[r.estado] = codigos.get(r.estado, 0) + 1
    ids = {_id(r) for r in respuestas}
    s.linea(
        "   ◀ "
        + "  ".join(f"{n} × HTTP {k}" for k, n in sorted(codigos.items()))
        + f"  ·  ids distintos: {len(ids)}"
    )
    s.comprobar("Criterio 6", "exactamente una responde 201 y las demás 200", codigos.get(201) == 1 and codigos.get(200, 0) == c.hilos - 1)  # fmt: skip
    s.comprobar("Criterio 6", "todas devuelven el mismo id", len(ids) == 1)
    n = c.sql(f"select count(*) from notificaciones where payload->>'productoId' = '{producto}'")
    a = c.sql(f"select count(*) from alertas where clave = '{producto}' and cerrada_at is null")
    if n and a:
        s.evidencia(
            "En la base de datos:", [f"notificaciones: {n[0][0]}  alertas activas: {a[0][0]}"]
        )
        s.comprobar("Criterio 6", "queda una sola notificación y una sola alerta activa", n[0][0] == "1" and a[0][0] == "1")  # fmt: skip
    s.pausa()


def _hu01_criterio7(c: Contexto, llave: str, var: str, corrida: str) -> None:
    s = c.salida
    s.criterio(
        7,
        "Dado que ocurre una falla interna al registrar la notificación o activar la alerta, "
        "cuando la API procesa el POST, entonces responde HTTP 500 con el mensaje "
        '"No fue posible registrar la notificación, intente de nuevo" y no deja ninguna '
        "notificación ni alerta registrada de forma parcial.",
    )
    if not (c.entorno.disponible and c.parar_bd):
        s.nota(
            "Escena omitida: provocar la falla exige apagar la base de datos del docker compose local"
        )
        s.nota("(use la opción por defecto; se desactiva con --sin-parar-bd). La prueba automática")
        s.nota("test_falla_interna_500 cubre este criterio.")
        s.pausa()
        return
    producto = f"HU01-C7-{corrida}"
    cuerpo = _stock(producto)
    s.nota("Falla provocada: se apaga la base de datos un momento (docker compose stop db).")
    if not c.entorno.parar_bd():
        s.comprobar("Criterio 7", "se pudo apagar la base de datos", False)
        return
    try:
        r, ok = c.http("Inventario", "POST", "/notificaciones", cuerpo, llave, var, 500, "Falla interna: el emisor recibe un mensaje controlado, sin detalles internos.")  # fmt: skip
        s.comprobar("Criterio 7", 'responde 500 con "No fue posible registrar la notificación, intente de nuevo"', ok and _mensaje(r) == "No fue posible registrar la notificación, intente de nuevo")  # fmt: skip
    finally:
        s.nota("Se vuelve a encender la base de datos (docker compose start db).")
        vuelve = c.entorno.iniciar_bd()
    s.comprobar("Criterio 7", "la base de datos volvió a responder", vuelve)
    n = c.sql(f"select count(*) from notificaciones where payload->>'productoId' = '{producto}'")
    a = c.sql(f"select count(*) from alertas where clave = '{producto}'")
    if n and a:
        s.evidencia("En la base de datos, del artículo de la solicitud fallida:", [f"notificaciones: {n[0][0]}  alertas: {a[0][0]}"])  # fmt: skip
        s.comprobar(
            "Criterio 7", "no quedó nada registrado a medias", n[0][0] == "0" and a[0][0] == "0"
        )
    r, ok = c.http("Inventario", "POST", "/notificaciones", cuerpo, llave, var, 201, "Con la base de vuelta, el mismo artículo se registra como nuevo (201, no 200).")  # fmt: skip
    s.comprobar("Criterio 7", "el servicio se recuperó y el artículo se registra como nuevo", ok)
    s.pausa()


def _hu01_criterio8(c: Contexto, llave: str, var: str, corrida: str, id_existente: Any) -> None:
    s = c.salida
    s.criterio(
        8,
        "Dado que la API recibe un evento, cuando termina de procesarlo, entonces deja en el log "
        "una línea con el resultado (REGISTRADA, ALERTA_YA_ACTIVA, ALERTA_CERRADA o RECHAZADA), "
        "el tipo, el destino, la clave de la alerta y el id de la notificación cuando exista.",
    )
    if not c.entorno.disponible:
        s.nota("Escena omitida: los registros se leen con docker compose logs (entorno local).")
        s.pausa()
        return
    producto = f"HU01-C8-{corrida}"
    c.api.enviar("POST", "/notificaciones", llave, _stock(producto))
    c.api.enviar("POST", "/notificaciones", llave, _stock(producto))
    c.api.enviar("POST", "/notificaciones", llave, _stock(producto, stockActual=-1))
    c.api.enviar("POST", "/notificaciones", llave, _stock(producto, evento="REPUESTO"))
    s.nota("Se enviaron cuatro eventos del mismo artículo: nuevo, repetido, inválido y reposición.")
    s.comando(f"docker compose logs api | grep {producto}", "Comando para verlo")
    lineas = [x for x in c.entorno.registros().splitlines() if producto in x and "resultado=" in x]
    lineas = [re.sub(r"^\S+\s+\|\s*", "", x) for x in lineas]
    lineas = [re.sub(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ \w+ \S+ ", "", x) for x in lineas]
    s.evidencia("Líneas del registro de la API:", [x[:150] for x in lineas])
    for resultado in ("REGISTRADA", "ALERTA_YA_ACTIVA", "RECHAZADA", "ALERTA_CERRADA"):
        linea = next((x for x in lineas if f"resultado={resultado}" in x), "")
        completa = all(k in linea for k in ("tipo=", "destino=", "clave=", "notificacion_id="))
        s.comprobar("Criterio 8", f"resultado={resultado} con tipo, destino, clave e id", bool(linea) and completa)  # fmt: skip
    s.pausa()


# ---------------------------------------------------------------------------------------------
HISTORIAS: dict[str, tuple[str, Callable[[Contexto], None]]] = {
    "01": ("HU-NOT-01", hu_01),
    "11": ("HU-NOT-11", hu_11),
}


def _parser() -> Any:
    parser = crear_parser(add_help=False)
    import argparse

    p = argparse.ArgumentParser(
        prog="python -m scripts.demo.criterios",
        description="Demo por criterios de aceptación de una historia de usuario.",
        parents=[parser],
    )
    p.add_argument("--hu", required=True, choices=[*HISTORIAS, "todas"], help="Historia: 01, 11 o todas")  # fmt: skip
    p.add_argument("--solo", default="", help="Solo estos criterios, separados por comas (ej. 3,4)")
    p.add_argument("--conservar", action="store_true", help="HU-11: no desactivar las llaves creadas")  # fmt: skip
    p.add_argument("--sin-parar-bd", action="store_true", help="HU-01 criterio 7: no apagar la base de datos")  # fmt: skip
    p.add_argument(
        "--hilos", type=int, default=10, help="HU-01 criterio 6: solicitudes simultáneas"
    )
    return p


def main(
    argv: Sequence[str] | None = None,
    http: httpx.Client | None = None,
    entorno: Entorno | None = None,
    escribir: Callable[[str], None] = print,
    leer: Callable[[str], str] = input,
) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    config = configuracion_de(args)
    salida = Salida(
        color=config.color and sys.stdout.isatty(),
        pausar=not config.rapido and sys.stdin.isatty(),
        escribir=escribir,
        leer=leer,
    )
    if args.preparar:
        try:
            llaves = preparar_llaves(Path.cwd())
        except (RuntimeError, OSError) as error:
            salida.linea(f"✗ {error}")
            return SIN_EJECUTAR
        salida.linea(f"✓ Llaves creadas y guardadas en .demo.env ({', '.join(llaves)})")
        config = configuracion_de(args)
    faltan = [rol for rol, llave in config.llaves.items() if not llave]
    if faltan:
        salida.linea(f"✗ Faltan las llaves de: {', '.join(faltan)}. Use --preparar (docker compose local)")  # fmt: skip
        salida.linea("  o defina DEMO_LLAVE_INVENTARIO, DEMO_LLAVE_FABRICACION y DEMO_LLAVE_ADMIN.")
        return SIN_EJECUTAR
    solo = {int(x) for x in args.solo.split(",") if x.strip().isdigit()}
    cliente = http or httpx.Client(base_url=config.url, timeout=20)
    contexto = Contexto(
        config, salida, ClienteApi(cliente), entorno or DockerLocal(Path.cwd()), solo,
        conservar=args.conservar, parar_bd=not args.sin_parar_bd, hilos=args.hilos,
    )  # fmt: skip
    seleccion = list(HISTORIAS) if args.hu == "todas" else [args.hu]
    try:
        salida.linea("═" * 68)
        salida.linea(f"  Notificaciones · Demo por criterios de aceptación · API: {config.url}")
        salida.linea("═" * 68)
        salida.comando(
            "set -a; source .demo.env; set +a          # llaves: DEMO_LLAVE_INVENTARIO, ...\n"
            f"export DEMO_URL={config.url}",
            "Preparación para copiar los curl de ejemplo",
        )
        if http is None and cliente.get("/health").status_code != 200:
            salida.linea("✗ La API no responde en /health")
            return SIN_EJECUTAR
        for clave in seleccion:
            salida.linea()
            HISTORIAS[clave][1](contexto)
    except httpx.TransportError:
        salida.linea(f"✗ No se pudo conectar a {config.url}. ¿Está levantada la API? (docker compose up --build)")  # fmt: skip
        return SIN_EJECUTAR
    finally:
        if http is None:
            cliente.close()
    return CORRECTO if salida.resumen() else COMPROBACION_FALLIDA


if __name__ == "__main__":
    raise SystemExit(main())

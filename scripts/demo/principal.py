"""Guion del demo: cada escena cuenta qué pasa, lo hace de verdad contra la API y lo comprueba."""

import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from scripts.demo.cola import Escucha
from scripts.demo.configuracion import Configuracion, cargar, descubrir_amqp, preparar_llaves
from scripts.demo.equipos_falsos import Administracion, ClienteApi, Fabricacion, Inventario
from scripts.demo.salida import Respuesta, Salida


def _id(r: Respuesta) -> str | None:
    return r.cuerpo.get("id") if isinstance(r.cuerpo, dict) else None


def _mensaje(r: Respuesta) -> str | None:
    return r.cuerpo.get("mensaje") if isinstance(r.cuerpo, dict) else None


def correr(
    config: Configuracion,
    salida: Salida,
    http: httpx.Client,
    escucha: Escucha,
    dormir: Callable[[float], None] = time.sleep,
) -> bool:
    api = ClienteApi(http)
    inventario = Inventario(config.llaves["inventario"], api, salida)
    fabricacion = Fabricacion(config.llaves["fabricacion"], api, salida)
    admin = Administracion(config.llaves["notificaciones"], api, salida)
    corrida = f"{time.strftime('%H%M%S')}-{uuid4().hex[:4]}"  # distinto en cada corrida
    articulo, condicion = f"DEMO-ACERO-{corrida}", f"DEMO-LINEA2-{corrida}"

    salida.titulo("Notificaciones · Demo con equipos falsos")
    salida.linea(f"   API: {config.url}")
    r = api.enviar("GET", "/health", None)
    if r.estado != 200:
        salida.linea(f"   ✗ La API no responde como se espera (GET /health → {r.estado})")
        return False
    info = api.enviar("GET", "/openapi.json", None).cuerpo
    if isinstance(info, dict):
        salida.linea(f"   {info['info']['title']} · contrato {info['info']['version']}")
    motivo = escucha.abrir()
    if motivo:
        salida.linea(f"   Cola: omitida ({motivo}). Se activa con AMQP_URL, o con --preparar "
                     "si la API corre en el docker compose local.")  # fmt: skip
    else:
        salida.linea("   Cola: escuchando una copia de las colas de los equipos")
    salida.pausa("Enter para empezar")

    # --- 1
    salida.escena(1, "Inventario detecta stock bajo",
                  "El equipo de Inventario ve que el acero bajó de su mínimo y avisa.")  # fmt: skip
    stock = inventario.stock_bajo(articulo, "Acero inoxidable 304", 4, 10)
    r1 = inventario.reportar(stock)
    ok = salida.respuesta(
        r1, 201, "Se registró la notificación y quedó activa una alerta para ese artículo."
    )
    salida.registrar("Escena 1", "stock bajo registrado (201)", ok)
    id_stock = _id(r1)
    salida.nota("Inventario no sabe si el mensaje llegó, así que lo manda otra vez (reintento).")
    r1b = inventario.reportar(stock)
    ok = salida.respuesta(
        r1b,
        200,
        "Ya había una alerta activa: no se crea otra notificación y se devuelve la original.",
    )
    salida.registrar(
        "Escena 1", "el reintento no duplica (200, mismo id)", ok and _id(r1b) == id_stock
    )
    salida.pausa()

    # --- 2
    salida.escena(2, "Lo que el módulo rechaza",
                  "Sin llave válida, con el rol equivocado o con datos mal formados.")  # fmt: skip
    salida.nota("La misma petición de la escena 1, pero con una llave inventada.")
    r2 = inventario.reportar(stock, llave="llave-inventada")
    ok = salida.respuesta(r2, 401, "Una llave que no existe no entra; la respuesta no da pistas.")
    salida.registrar("Escena 2", "llave inválida (401)", ok)
    r2b = inventario.pedir(
        "POST", "/notificaciones", fabricacion.condicion_urgente("X-1", "No le corresponde")
    )
    ok = salida.respuesta(
        r2b, 403, "Inventario no puede emitir condiciones urgentes: son de Fabricación."
    )
    salida.registrar("Escena 2", "tipo de otro equipo (403)", ok)
    r2c = inventario.reportar(inventario.stock_bajo("articulo con espacios", "", -5, 10))
    ok = salida.respuesta(
        r2c, 422, "Los datos no cumplen las reglas; la respuesta dice qué campo falla."
    )
    if isinstance(r2c.cuerpo, dict):
        for e in r2c.cuerpo.get("errores", []):
            salida.nota(f"{e['campo']}: {e['error']}")
    salida.registrar("Escena 2", "datos inválidos (422)", ok)
    salida.pausa()

    # --- 3
    salida.escena(3, "Fabricación reporta una condición urgente",
                  "Fabricación avisa que una línea se detuvo. Es otro tipo y otro destino.")  # fmt: skip
    urgente = fabricacion.condicion_urgente(condicion, "Línea 2 detenida por falla de motor")
    r3 = fabricacion.reportar(urgente)
    ok = salida.respuesta(
        r3, 201, "Registrada. Esta alerta vence en 60 minutos (la de stock, en 24 horas)."
    )
    salida.registrar("Escena 3", "condición urgente registrada (201)", ok)
    id_urgente = _id(r3)
    salida.pausa()

    # --- 4
    salida.escena(4, "Los mensajes llegan a la cola de cada equipo",
                  "Cada notificación se publica en la cola de su destino con su id y su tipo.")  # fmt: skip
    if not escucha.activa:
        salida.nota(f"Escena omitida: la cola no está disponible para esta demo ({motivo}).")
    else:
        for destino, id_, tipo in (("inventario", id_stock, "STOCK_BAJO_INSUMO"),
                                   ("fabricacion", id_urgente, "CONDICION_URGENTE")):  # fmt: skip
            mensaje = escucha.esperar(destino, id_) if id_ else None
            llego = mensaje == {"id": id_, "tipo": tipo}
            detalle = f"id {mensaje['id']}  ·  tipo {mensaje['tipo']}" if mensaje else "no llegó"
            salida.linea(f"   cola notif.{destino}  ◀  {detalle}  {'✓' if llego else '✗'}")
            salida.registrar("Escena 4", f"llegó a notif.{destino}", llego)
    salida.pausa()

    # --- 5
    salida.escena(5, "Inventario repone el artículo",
                  "Cuando el stock se normaliza, Inventario cierra la alerta; si vuelve a bajar, se notifica de nuevo.")  # fmt: skip
    r5 = inventario.reportar(
        inventario.stock_bajo(articulo, "Acero inoxidable 304", 40, 10, evento="REPUESTO")
    )
    ok = salida.respuesta(r5, 200, "La alerta se cerró; la notificación original sigue guardada.")
    salida.registrar(
        "Escena 5", "alerta resuelta (200)", ok and _mensaje(r5) == "Alerta resuelta correctamente"
    )
    r5b = inventario.reportar(stock)
    ok = salida.respuesta(
        r5b, 201, "Con la alerta cerrada, el nuevo aviso sí genera otra notificación."
    )
    salida.registrar(
        "Escena 5", "nuevo aviso tras la reposición (201, otro id)", ok and _id(r5b) != id_stock
    )
    salida.pausa()

    # --- 6
    salida.escena(6, "El ciclo de mantenimiento",
                  "Cada 5 minutos se cierran las alertas vencidas y se reintentan las publicaciones pendientes.")  # fmt: skip
    r6 = inventario.pedir("POST", "/notificaciones/ciclo")
    ok = salida.respuesta(r6, 403, "Solo la administración de Notificaciones puede ejecutarlo.")
    salida.registrar("Escena 6", "el ciclo es solo de administración (403)", ok)
    r6b = admin.ejecutar_ciclo()
    ok = salida.respuesta(
        r6b, 200, "Resumen: alertas vencidas que cerró y notificaciones que publicó."
    )
    salida.registrar("Escena 6", "ciclo ejecutado (200)", ok)
    salida.pausa()

    # --- 7 (opcional)
    if config.broker_caido:
        _escena_broker_caido(config, salida, inventario, admin, escucha, dormir, corrida)
    return salida.resumen()


def _escena_broker_caido(
    config: Configuracion,
    salida: Salida,
    inventario: Inventario,
    admin: Administracion,
    escucha: Escucha,
    dormir: Callable[[float], None],
    corrida: str,
) -> None:
    salida.escena(7, "La cola se cae y el módulo no pierde nada",
                  "Si el broker falla, el emisor igual recibe su respuesta y la notificación espera su turno.")  # fmt: skip
    salida.pedir_accion("Apague RabbitMQ en otra terminal (docker compose stop rabbitmq)")
    pendiente = f"DEMO-PENDIENTE-{corrida}"
    r = inventario.reportar(inventario.stock_bajo(pendiente, "Rodamiento 6204", 1, 8))
    ok = salida.respuesta(
        r, 201, "Respondió igual: la notificación quedó guardada, pendiente de publicar."
    )
    salida.registrar("Escena 7", "con la cola caída el POST responde 201", ok)
    salida.pedir_accion("Vuelva a encender RabbitMQ (docker compose start rabbitmq)")
    if escucha.activa:
        # Las colas temporales del demo se borraron con el broker: se vuelve a suscribir antes
        # de que el ciclo publique.
        salida.nota("Volviendo a suscribir el demo a las colas...")
        escucha.reabrir()
    salida.nota(
        f"Esperando {config.espera_reintento_s} s: el ciclo solo reintenta notificaciones de más de 1 minuto."
    )
    for restante in range(config.espera_reintento_s, 0, -10):
        salida.linea(f"      ... {restante} s")
        dormir(min(10, restante))
    rc = admin.ejecutar_ciclo()
    ok = salida.respuesta(rc, 200, "El ciclo volvió a intentar la publicación.")
    publicadas = rc.cuerpo.get("publicadas", 0) if isinstance(rc.cuerpo, dict) else 0
    salida.registrar("Escena 7", "el ciclo publicó la pendiente", ok and publicadas >= 1)
    id_ = _id(r)
    if escucha.activa and id_:
        mensaje: Any = escucha.esperar("inventario", id_)
        detalle = f"id {mensaje['id']}  ·  tipo {mensaje['tipo']}" if mensaje else "no llegó"
        salida.linea(f"   cola notif.inventario  ◀  {detalle}")
        salida.registrar("Escena 7", "el mensaje llegó a la cola", mensaje is not None)


def main(
    argv: Sequence[str] | None = None,
    http: httpx.Client | None = None,
    escribir: Callable[[str], None] = print,
    leer: Callable[[str], str] = input,
    dormir: Callable[[float], None] = time.sleep,
) -> int:
    argumentos = sys.argv[1:] if argv is None else argv
    config, preparar = cargar(argumentos)
    salida = Salida(
        color=config.color and sys.stdout.isatty(),
        pausar=not config.rapido and sys.stdin.isatty(),
        escribir=escribir,
        leer=leer,
    )
    if preparar:
        try:
            llaves = preparar_llaves(Path.cwd())
        except (RuntimeError, OSError) as error:
            salida.linea(f"✗ {error}")
            salida.linea("  Genere las llaves a mano y expórtelas: DEMO_LLAVE_INVENTARIO, "
                         "DEMO_LLAVE_FABRICACION y DEMO_LLAVE_ADMIN.")  # fmt: skip
            return 2
        salida.linea(f"✓ Llaves creadas y guardadas en .demo.env ({', '.join(llaves)})")
        config, _ = cargar(argumentos)
    faltan = [rol for rol, llave in config.llaves.items() if not llave]
    if faltan:
        salida.linea(f"✗ Faltan las llaves de: {', '.join(faltan)}.")
        salida.linea("  Use --preparar (docker compose local) o defina DEMO_LLAVE_INVENTARIO, "
                     "DEMO_LLAVE_FABRICACION y DEMO_LLAVE_ADMIN.")  # fmt: skip
        return 2
    if not config.amqp_url and urlsplit(config.url).hostname in ("localhost", "127.0.0.1"):
        config = replace(config, amqp_url=descubrir_amqp(Path.cwd()))
    cliente = http or httpx.Client(base_url=config.url, timeout=15)
    escucha = Escucha(config.amqp_url)
    try:
        return 0 if correr(config, salida, cliente, escucha, dormir) else 1
    except httpx.TransportError:
        salida.linea(f"✗ No se pudo conectar a {config.url}. ¿Está levantada la API? "
                     "(docker compose up --build)")  # fmt: skip
        return 2
    finally:
        escucha.cerrar()
        if http is None:
            cliente.close()

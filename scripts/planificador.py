"""Planificador: corre el ciclo del módulo (cierra alertas vencidas y reintenta publicaciones).

Es un proceso aparte de la API (DAS: API, worker y planificador separados) que ejecuta
`ServicioNotificaciones.ejecutar_ciclo()` cada `CICLO_INTERVALO_S` segundos (300 por defecto).
Habla directo con el servicio: no necesita llave ni pasa por HTTP. Si dos instancias corren a la
vez, el ciclo ya evita procesar dos veces el mismo registro.

    python -m scripts.planificador               # corre hasta recibir SIGTERM o Ctrl+C
    python -m scripts.planificador --una-vez     # un solo ciclo y termina (útil para probar)
    python -m scripts.planificador --verificar   # healthcheck: ¿el último ciclo es reciente?
"""

import argparse
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

log = logging.getLogger("planificador")

# Se actualiza tras cada ciclo que termina. Relativo al directorio de trabajo (en la imagen,
# /app/run, que pertenece al usuario de la app); no se usa /tmp, que es de escritura pública.
LATIDO = Path(os.environ.get("PLANIFICADOR_LATIDO", "run/planificador.latido"))


class _Servicio(Protocol):
    def ejecutar_ciclo(self) -> tuple[dict[str, int], list[str]]: ...


def un_ciclo(servicio: _Servicio, latido: Path | None = LATIDO) -> bool:
    """Ejecuta el ciclo una vez. Nunca lanza: un fallo se registra y el siguiente lo reintenta."""
    try:
        resumen, errores = servicio.ejecutar_ciclo()
    except Exception:
        log.exception("Falló el ciclo completo; se reintenta en el siguiente")
        return False
    detalle = ", ".join(f"{nombre}={cantidad}" for nombre, cantidad in resumen.items())
    if errores:
        log.warning("Ciclo con tareas fallidas (%s): %s", ", ".join(errores), detalle)
    else:
        log.info("Ciclo completado: %s", detalle or "sin tareas")
    if latido is not None:
        latido.parent.mkdir(parents=True, exist_ok=True)
        latido.touch()
    return not errores


def ejecutar(
    servicio: _Servicio,
    intervalo_s: float,
    parar: threading.Event,
    latido: Path | None = LATIDO,
    reloj: Callable[[], float] = time.monotonic,
) -> None:
    """Repite el ciclo cada `intervalo_s`, contando lo que tardó cada uno, hasta `parar`."""
    log.info("Planificador iniciado: un ciclo cada %s s", intervalo_s)
    while not parar.is_set():
        inicio = reloj()
        un_ciclo(servicio, latido)
        parar.wait(max(0.0, intervalo_s - (reloj() - inicio)))
    log.info("Planificador detenido")


def latido_reciente(intervalo_s: float, latido: Path = LATIDO, ahora: float | None = None) -> bool:
    """Sano si el último ciclo terminó hace menos de tres intervalos."""
    if not latido.exists():
        return False
    actual = time.time() if ahora is None else ahora
    return actual - latido.stat().st_mtime < 3 * intervalo_s + 30


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planificador del ciclo de Notificaciones")
    parser.add_argument("--una-vez", action="store_true", help="Un solo ciclo y termina")
    parser.add_argument(
        "--verificar", action="store_true", help="Healthcheck: ¿hay latido reciente?"
    )
    parser.add_argument("--intervalo", type=float, help="Segundos entre ciclos (CICLO_INTERVALO_S)")
    args = parser.parse_args(argv)

    from app.config import get_settings

    ajustes = get_settings()
    intervalo = args.intervalo or ajustes.ciclo_intervalo_s
    if args.verificar:
        return 0 if latido_reciente(intervalo) else 1

    logging.basicConfig(
        level=ajustes.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    from app.api.deps import get_servicio_notificaciones
    from app.infrastructure.broker import cerrar_publicador

    servicio = get_servicio_notificaciones()
    if args.una_vez:
        try:
            return 0 if un_ciclo(servicio, None) else 1
        finally:
            cerrar_publicador()

    parar = threading.Event()
    for senal in (signal.SIGTERM, signal.SIGINT):
        signal.signal(senal, lambda *_: parar.set())
    try:
        ejecutar(servicio, intervalo, parar)
    finally:
        cerrar_publicador()
    return 0


if __name__ == "__main__":
    sys.exit(main())

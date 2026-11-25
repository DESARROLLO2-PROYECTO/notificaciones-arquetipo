"""Configuración del demo: argumentos, variables de entorno y el archivo `.demo.env`."""

import argparse
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

_LLAVE = re.compile(r"[A-Za-z0-9_-]{32,}")  # la llave generada, de 43 caracteres
ARCHIVO_LLAVES = Path(".demo.env")
URL_POR_DEFECTO = "http://localhost:8090"
ROLES = ("inventario", "fabricacion", "notificaciones")
_VARIABLE_LLAVE = {
    "inventario": "DEMO_LLAVE_INVENTARIO",
    "fabricacion": "DEMO_LLAVE_FABRICACION",
    "notificaciones": "DEMO_LLAVE_ADMIN",
}


@dataclass(frozen=True)
class Configuracion:
    url: str
    llaves: Mapping[str, str]  # rol -> llave
    amqp_url: str | None
    rapido: bool
    color: bool
    broker_caido: bool
    espera_reintento_s: int


def leer_archivo(ruta: Path) -> dict[str, str]:
    """Lee líneas CLAVE=valor; ignora vacías y comentarios."""
    valores: dict[str, str] = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                valores[clave.strip()] = valor.strip()
    return valores


def crear_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.demo",
        description="Demo: equipos falsos le piden notificaciones al módulo de Notificaciones.",
    )
    parser.add_argument(
        "--url", help=f"Dirección de la API (variable DEMO_URL; por defecto {URL_POR_DEFECTO})"
    )
    parser.add_argument(
        "--preparar",
        action="store_true",
        help="Genera las 3 llaves en el docker compose local y las guarda en .demo.env",
    )
    parser.add_argument("--rapido", action="store_true", help="Sin pausas entre escenas")
    parser.add_argument("--sin-color", action="store_true", help="Salida sin colores")
    parser.add_argument(
        "--broker-caido",
        action="store_true",
        help="Agrega la escena en la que se apaga RabbitMQ (pide hacerlo a mano)",
    )
    parser.add_argument(
        "--espera-reintento",
        type=int,
        default=65,
        help="Segundos que se espera antes del reintento en la escena del broker caído",
    )
    return parser


def cargar(
    argv: Sequence[str], entorno: Mapping[str, str] | None = None, archivo: Path | None = None
) -> tuple[Configuracion, bool]:
    """Devuelve la configuración y si se pidió `--preparar`.

    Prioridad: argumento, variable de entorno, archivo `.demo.env`.
    """
    args = crear_parser().parse_args(argv)
    entorno = os.environ if entorno is None else entorno
    guardado = leer_archivo(ARCHIVO_LLAVES if archivo is None else archivo)

    def valor(nombre: str) -> str | None:
        return entorno.get(nombre) or guardado.get(nombre) or None

    llaves = {rol: valor(var) or "" for rol, var in _VARIABLE_LLAVE.items()}
    color = not args.sin_color and "NO_COLOR" not in entorno
    config = Configuracion(
        url=(args.url or valor("DEMO_URL") or URL_POR_DEFECTO).rstrip("/"),
        llaves=llaves,
        amqp_url=valor("AMQP_URL"),
        rapido=args.rapido,
        color=color,
        broker_caido=args.broker_caido,
        espera_reintento_s=args.espera_reintento,
    )
    return config, args.preparar


def preparar_llaves(raiz: Path, archivo: Path | None = None) -> dict[str, str]:
    """Crea una llave por rol dentro del contenedor `api` y las guarda en `.demo.env`."""
    llaves: dict[str, str] = {}
    for rol in ROLES:
        resultado = subprocess.run(  # noqa: S603 - comando fijo, sin entrada del usuario
            ["docker", "compose", "exec", "-T", "api", "python", "-m", "scripts.crear_api_key",
             "--rol", rol],
            cwd=raiz, capture_output=True, text=True, check=False,
        )  # fmt: skip
        lineas = _LLAVE.findall(resultado.stdout)
        if resultado.returncode != 0 or not lineas:
            detalle = (resultado.stderr or resultado.stdout).strip().splitlines()
            raise RuntimeError(
                f"No se pudo crear la llave de {rol}: {detalle[-1] if detalle else 'sin detalle'}"
            )
        llaves[rol] = lineas[0]
    contenido = "# Llaves del demo (no se suben a git)\n" + "".join(
        f"{_VARIABLE_LLAVE[rol]}={llave}\n" for rol, llave in llaves.items()
    )
    (ARCHIVO_LLAVES if archivo is None else archivo).write_text(contenido, encoding="utf-8")
    return llaves

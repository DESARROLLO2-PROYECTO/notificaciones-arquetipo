"""Verifica la conexión al broker: `python -m scripts.verificar_cola [--url amqps://...]`."""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence

from app.infrastructure.broker import _ERRORES_BROKER, sondear


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sonda del broker de mensajes (CloudAMQP)")
    parser.add_argument("--url", default=os.environ.get("AMQP_URL"), help="Por defecto AMQP_URL")
    parser.add_argument("--timeout", type=float, default=5.0, help="Segundos por operación")
    args = parser.parse_args(argv)
    if not args.url:
        print("Falta la URL del broker: use --url o la variable AMQP_URL", file=sys.stderr)
        return 1
    try:
        segundos = asyncio.run(sondear(args.url, args.timeout))
    except _ERRORES_BROKER as error:
        # Sin la URL ni el detalle del driver: pueden incluir la clave.
        print(f"No fue posible usar el broker ({type(error).__name__})", file=sys.stderr)
        return 1
    print(f"Broker OK: publicación y consumo de la sonda en {segundos * 1000:.0f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Ejecutar: python -m app.cli.api_keys generar --rol inventario."""

import argparse
import sys
from collections.abc import Sequence

from app.domain.api_key_service import ApiKeyService, validar_rol
from app.domain.errores import ErrorDominio
from app.infrastructure.db import transaccion
from app.infrastructure.repositories import ApiKeyRepo


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Administrar API Keys (HU-NOT-11)")
    comandos = parser.add_subparsers(dest="comando", required=True)
    generar = comandos.add_parser("generar", help="Generar y mostrar una llave una sola vez")
    generar.add_argument("--rol", required=True, help="inventario, fabricacion o notificaciones")
    desactivar = comandos.add_parser("desactivar", help="Desactivar una llave por su identificador")
    desactivar.add_argument("--id", required=True, type=int, help="Identificador de la API Key")
    args = parser.parse_args(argv)
    if args.comando == "desactivar" and args.id < 1:
        parser.error("El identificador debe ser un entero positivo")

    try:
        if args.comando == "generar":
            validar_rol(args.rol)
        with transaccion() as session:
            servicio = ApiKeyService(ApiKeyRepo(session))
            if args.comando == "generar":
                resultado = servicio.generar(args.rol)
            else:
                servicio.desactivar(args.id)
    except ErrorDominio as exc:
        print(exc.mensaje, file=sys.stderr)
        return 1
    except Exception:
        # No imprimir excepciones de drivers ni parámetros SQL/configuración.
        print(
            "No fue posible administrar la API Key; revise la conexión y las migraciones",
            file=sys.stderr,
        )
        return 1

    # Solo se muestra el secreto después de confirmar el commit.
    if args.comando == "generar":
        print(
            f"ID: {resultado.id}\nRol: {resultado.rol}\nCreada: {resultado.creada_at.isoformat()}"
        )
        print(f"API Key (se muestra una sola vez): {resultado.llave}")
    else:
        print("API Key desactivada correctamente")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

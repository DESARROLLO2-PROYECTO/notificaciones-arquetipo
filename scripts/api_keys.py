"""Controlador de los comandos de administración de API Keys."""

import argparse
import sys
from collections.abc import Sequence
from typing import Literal

from app.domain.api_key_service import ApiKeyService, validar_rol
from app.domain.errores import ErrorDominio
from app.infrastructure.db import transaccion
from app.infrastructure.repositories import ApiKeyRepo

type Comando = Literal["generar", "desactivar"]


def _agregar_argumento(parser: argparse.ArgumentParser, comando: Comando) -> None:
    if comando == "generar":
        parser.add_argument("--rol", required=True, help="inventario, fabricacion o notificaciones")
    else:
        parser.add_argument("--id", required=True, type=int, help="Identificador de la API Key")


def main(argv: Sequence[str] | None = None, *, comando: Comando | None = None) -> int:
    parser = argparse.ArgumentParser(description="Administrar API Keys (HU-NOT-11)")
    if comando is None:
        comandos = parser.add_subparsers(dest="comando", required=True)
        generar = comandos.add_parser("generar", help="Generar y mostrar una llave una sola vez")
        desactivar = comandos.add_parser("desactivar", help="Desactivar una llave por su ID")
        _agregar_argumento(generar, "generar")
        _agregar_argumento(desactivar, "desactivar")
    else:
        _agregar_argumento(parser, comando)
        parser.set_defaults(comando=comando)
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

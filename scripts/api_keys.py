"""Controlador de los comandos de administración de API Keys."""

import argparse
import sys
from collections.abc import Sequence
from typing import Literal

from app.domain.api_key_service import ApiKeyService, validar_rol
from app.domain.errores import ErrorDominio
from app.infrastructure.db import transaccion
from app.infrastructure.repositories import ApiKeyRepo

type Comando = Literal["generar", "desactivar", "listar"]


def _agregar_argumento(parser: argparse.ArgumentParser, comando: Comando) -> None:
    if comando == "generar":
        parser.add_argument("--rol", required=True, help="inventario, fabricacion o notificaciones")
    elif comando == "desactivar":
        parser.add_argument("--id", required=True, type=int, help="Identificador de la API Key")


def main(argv: Sequence[str] | None = None, *, comando: Comando | None = None) -> int:
    parser = argparse.ArgumentParser(description="Administrar API Keys (HU-NOT-11)")
    if comando is None:
        comandos = parser.add_subparsers(dest="comando", required=True)
        generar = comandos.add_parser("generar", help="Generar y mostrar una llave una sola vez")
        desactivar = comandos.add_parser("desactivar", help="Desactivar una llave por su ID")
        comandos.add_parser("listar", help="Listar las llaves (sin su valor)")
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
            elif args.comando == "desactivar":
                servicio.desactivar(args.id)
            else:
                llaves = servicio.listar()
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
    elif args.comando == "desactivar":
        print("API Key desactivada correctamente")
    else:
        print(f"{'ID':>4}  {'ROL':<15} {'PREFIJO':<9} {'ESTADO':<9} CREADA")
        for k in llaves:
            estado = "activa" if k.activa else "inactiva"
            print(f"{k.id:>4}  {k.rol:<15} {k.prefijo:<9} {estado:<9} {k.creada_at.isoformat()}")
    return 0

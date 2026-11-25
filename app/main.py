"""Punto de entrada: configura el log y expone `app` para uvicorn (app.main:app)."""

import logging

from fastapi import FastAPI

from app.api.aplicacion import construir_app
from app.config import get_settings
from app.infrastructure.log_acceso import OcultarQuery


def create_app() -> FastAPI:
    logging.basicConfig(
        level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    acceso = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, OcultarQuery) for f in acceso.filters):
        acceso.addFilter(OcultarQuery())
    return construir_app()


app = create_app()

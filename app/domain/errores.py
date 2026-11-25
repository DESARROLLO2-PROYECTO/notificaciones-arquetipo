"""Excepciones de dominio que la capa API traduce a respuestas HTTP."""


class ErrorDominio(Exception):
    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje


class NoEncontrado(ErrorDominio):
    """404"""


class NombreDuplicado(ErrorDominio):
    """409"""


class NoAutenticado(ErrorDominio):
    """401"""

    def __init__(self, motivo: str, rol: str | None = None) -> None:
        super().__init__("Acceso denegado")
        self.motivo = motivo
        self.rol = rol


class ClaveDuplicada(ErrorDominio):
    """409"""


class TipoNotificacionInvalido(ErrorDominio):
    """409"""


class ClaveAlertaFaltante(ErrorDominio):
    """400"""


class ErrorConcurrenciaAlerta(Exception):
    """Lanzada por el repositorio/UoW cuando choca el índice único parcial en Postgres."""

"""Excepciones de dominio; la capa API las traduce a HTTP (404/409)."""


class ErrorDominio(Exception):
    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje


class NoEncontrado(ErrorDominio):
    """404"""


class NombreDuplicado(ErrorDominio):
    """409"""

class ClaveDuplicada(ErrorDominio):
    """409"""


class TipoNotificacionInvalido(ErrorDominio):
    """409"""
    

class ClaveAlertaFaltante(ErrorDominio):
    """400"""

class ErrorConcurrenciaAlerta(Exception):
    """Lanzada por el repositorio/UoW cuando choca el índice único parcial en Postgres."""

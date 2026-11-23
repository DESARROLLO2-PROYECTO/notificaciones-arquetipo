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

"""HU-NOT-12: Autenticacion de las llaves y permisos de equipos."""

import hashlib
from typing import Protocol

from app.domain.errores import NoAutenticado

_EMISOR_POR_TIPO = {
    "STOCK_BAJO_INSUMO": "inventario",
    "STOCK_BAJO_PRODUCTO": "inventario",
    "ACUMULACION_PEDIDOS": "inventario",
    "CONDICION_URGENTE": "fabricacion",
}


class AutenticacionRepository(Protocol):
    def obtener_rol_y_estado_por_hash(self, hash_llave: str) -> tuple[str, bool] | None: ...


class AutenticacionService:
    def __init__(self, repo: AutenticacionRepository) -> None:
        self._repo = repo

    def autenticar(self, llave: str | None) -> str:
        if llave is None or not llave.strip():
            raise NoAutenticado("sin llave")

        hash_llave = hashlib.sha256(llave.encode("utf-8")).hexdigest()
        registro = self._repo.obtener_rol_y_estado_por_hash(hash_llave)
        if registro is None:
            raise NoAutenticado("llave inválida")

        rol, activa = registro
        if not activa:
            raise NoAutenticado("llave desactivada", rol)
        return rol

    @staticmethod
    def puede_enviar(rol: str, tipo: str) -> bool:
        return _EMISOR_POR_TIPO.get(tipo) == rol

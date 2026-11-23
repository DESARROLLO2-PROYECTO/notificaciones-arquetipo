"""HU-NOT-12: Autenticacion de las llaves y permisos de equipos."""

import hashlib
from typing import Protocol

_EMISOR_POR_TIPO = {
    "STOCK_BAJO_INSUMO": "inventario",
    "STOCK_BAJO_PRODUCTO": "inventario",
    "ACUMULACION_PEDIDOS": "inventario",
    "CONDICION_URGENTE": "fabricacion",
}


class AutenticacionRepository(Protocol):
    def obtener_activa_por_hash(self, hash_llave: str) -> str | None: ...


class AutenticacionService:
    def __init__(self, repo: AutenticacionRepository) -> None:
        self._repo = repo

    def autenticar(self, llave: str) -> str | None:
        hash_llave = hashlib.sha256(llave.encode("utf-8")).hexdigest()
        return self._repo.obtener_activa_por_hash(hash_llave)

    @staticmethod
    def puede_enviar(rol: str, tipo: str) -> bool:
        return _EMISOR_POR_TIPO.get(tipo) == rol

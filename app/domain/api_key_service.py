"""HU-NOT-11: administración de llaves. El dominio no depende de frameworks."""

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.errores import ErrorDominio, NoEncontrado
from app.domain.puertos import ApiKeyRepository, NuevaApiKey

ROLES = ("inventario", "fabricacion", "notificaciones")


class RolNoValido(ErrorDominio):
    pass


class LimiteLlavesActivas(ErrorDominio):
    pass


def validar_rol(rol: str) -> None:
    if rol not in ROLES:
        raise RolNoValido("Rol no válido")


@dataclass(frozen=True)
class ApiKeyGenerada:
    id: int
    rol: str
    creada_at: datetime
    llave: str = field(repr=False)


class ApiKeyService:
    def __init__(self, repo: ApiKeyRepository) -> None:
        self._repo = repo

    def generar(self, rol: str) -> ApiKeyGenerada:
        validar_rol(rol)
        # El bloqueo dura hasta el commit: dos scripts no pueden superar el límite.
        equipo_id = self._repo.bloquear_equipo(rol)
        if self._repo.contar_activas(equipo_id) >= 2:
            raise LimiteLlavesActivas("Ya existen dos llaves activas para este rol")
        llave = secrets.token_urlsafe(32)  # 32 bytes aleatorios, codificados en texto.
        creada_at = datetime.now(UTC)
        registro = NuevaApiKey(
            equipo_id=equipo_id,
            hash=hashlib.sha256(llave.encode("utf-8")).hexdigest(),
            creada_at=creada_at,
        )
        id = self._repo.crear(registro)
        return ApiKeyGenerada(id=id, rol=rol, creada_at=creada_at, llave=llave)

    def desactivar(self, id: int) -> None:
        if not self._repo.desactivar(id):
            raise NoEncontrado("API Key no encontrada")

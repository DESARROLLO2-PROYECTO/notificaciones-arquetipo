import base64
import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.domain.api_key_service import (
    ROLES,
    ApiKeyService,
    LimiteLlavesActivas,
    RolNoValido,
)
from app.domain.errores import NoEncontrado


class FakeApiKeyRepo:
    def __init__(self):
        self.registros = {}
        self.inactivas = set()
        self.bloqueados = []

    def bloquear_equipo(self, rol):
        self.bloqueados.append(rol)
        return ROLES.index(rol) + 1

    def contar_activas(self, equipo_id):
        return sum(
            r.equipo_id == equipo_id and id not in self.inactivas
            for id, r in self.registros.items()
        )

    def crear(self, llave):
        id = len(self.registros) + 1
        self.registros[id] = llave
        return id

    def desactivar(self, id):
        if id not in self.registros:
            return False
        self.inactivas.add(id)
        return True


@pytest.mark.parametrize("rol", ROLES)
def test_genera_32_bytes_guarda_solo_hash_y_fecha_utc(rol):
    repo = FakeApiKeyRepo()
    antes = datetime.now(UTC)
    resultado = ApiKeyService(repo).generar(rol)
    guardada = repo.registros[resultado.id]

    assert len(base64.urlsafe_b64decode(resultado.llave + "=")) == 32
    assert guardada.hash == hashlib.sha256(resultado.llave.encode()).hexdigest()
    assert guardada.prefijo == resultado.llave[:8]
    assert guardada.equipo_id == ROLES.index(rol) + 1
    assert antes <= guardada.creada_at <= datetime.now(UTC)
    assert guardada.creada_at.utcoffset().total_seconds() == 0
    assert resultado.creada_at == guardada.creada_at
    assert resultado.rol == rol
    assert resultado.llave not in repr(resultado)
    assert resultado.llave not in repr(guardada)
    assert repo.bloqueados == [rol]


@pytest.mark.parametrize("rol", ["", "otro", "admin", "Inventario", "fabricación"])
def test_rol_invalido_no_accede_al_repositorio(rol):
    repo = FakeApiKeyRepo()
    with pytest.raises(RolNoValido, match="^Rol no válido$"):
        ApiKeyService(repo).generar(rol)
    assert repo.bloqueados == []
    assert repo.registros == {}


def test_limite_por_rol_y_rotacion_sin_invalidar_la_otra_llave():
    repo = FakeApiKeyRepo()
    servicio = ApiKeyService(repo)
    primera = servicio.generar("inventario")
    segunda = servicio.generar("inventario")
    assert primera.llave != segunda.llave
    with pytest.raises(LimiteLlavesActivas, match="Ya existen dos llaves activas para este rol"):
        servicio.generar("inventario")
    assert len(repo.registros) == 2
    servicio.generar("fabricacion")
    original = replace(repo.registros[primera.id])
    servicio.desactivar(primera.id)
    servicio.desactivar(primera.id)
    tercera = servicio.generar("inventario")
    assert tercera.llave not in {primera.llave, segunda.llave}
    assert repo.registros[primera.id] == original
    assert segunda.id not in repo.inactivas
    assert repo.contar_activas(1) == 2


def test_desactivar_inexistente():
    with pytest.raises(NoEncontrado, match="API Key no encontrada"):
        ApiKeyService(FakeApiKeyRepo()).desactivar(999)

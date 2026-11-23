import hashlib

import pytest

from app.domain.autenticacion_service import AutenticacionService


class FakeAutenticacionRepo:
    def __init__(self, roles_por_hash: dict[str, str]) -> None:
        self._roles_por_hash = roles_por_hash

    def obtener_activa_por_hash(self, hash_llave: str) -> str | None:
        return self._roles_por_hash.get(hash_llave)


def test_autenticar_devuelve_el_rol_de_una_llave_activa():
    llave = "llave-de-prueba"
    hash_llave = hashlib.sha256(llave.encode("utf-8")).hexdigest()
    repo = FakeAutenticacionRepo({hash_llave: "inventario"})

    assert AutenticacionService(repo).autenticar(llave) == "inventario"


def test_autenticar_devuelve_none_si_no_hay_coincidencia_activa():
    repo = FakeAutenticacionRepo({})

    assert AutenticacionService(repo).autenticar("llave-sin-coincidencia") is None


@pytest.mark.parametrize(
    ("tipo", "emisor"),
    [
        ("STOCK_BAJO_INSUMO", "inventario"),
        ("STOCK_BAJO_PRODUCTO", "inventario"),
        ("ACUMULACION_PEDIDOS", "inventario"),
        ("CONDICION_URGENTE", "fabricacion"),
    ],
)
@pytest.mark.parametrize("rol", ["inventario", "fabricacion", "notificaciones"])
def test_solo_el_emisor_puede_enviar_el_tipo(tipo, emisor, rol):
    assert AutenticacionService.puede_enviar(rol, tipo) is (rol == emisor)


def test_no_permite_enviar_un_tipo_desconocido():
    assert AutenticacionService.puede_enviar("inventario", "TIPO_DESCONOCIDO") is False

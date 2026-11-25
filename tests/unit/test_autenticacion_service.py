import hashlib

import pytest

from app.domain.autenticacion_service import AutenticacionService
from app.domain.errores import NoAutenticado


class FakeAutenticacionRepo:
    def __init__(self, llaves_por_hash: dict[str, tuple[str, bool]]) -> None:
        self._llaves_por_hash = llaves_por_hash

    def obtener_rol_y_estado_por_hash(self, hash_llave: str) -> tuple[str, bool] | None:
        return self._llaves_por_hash.get(hash_llave)


def test_autenticar_devuelve_el_rol_de_una_llave_activa():
    llave = "llave-de-prueba"
    hash_llave = hashlib.sha256(llave.encode("utf-8")).hexdigest()
    repo = FakeAutenticacionRepo({hash_llave: ("inventario", True)})

    assert AutenticacionService(repo).autenticar(llave) == "inventario"


@pytest.mark.parametrize(
    ("llave", "motivo", "rol"),
    [
        (None, "sin llave", None),
        ("", "sin llave", None),
        ("  ", "sin llave", None),
        ("llave-sin-coincidencia", "llave inválida", None),
        ("llave-retirada", "llave desactivada", "inventario"),
    ],
)
def test_autenticar_distingue_el_motivo_del_rechazo(llave, motivo, rol):
    hash_retirada = hashlib.sha256(b"llave-retirada").hexdigest()
    repo = FakeAutenticacionRepo({hash_retirada: ("inventario", False)})

    with pytest.raises(NoAutenticado, match="^Acceso denegado$") as error:
        AutenticacionService(repo).autenticar(llave)
    assert error.value.motivo == motivo
    assert error.value.rol == rol


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

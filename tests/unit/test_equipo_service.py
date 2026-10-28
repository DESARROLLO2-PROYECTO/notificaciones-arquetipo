import pytest

from app.domain.equipo_service import EquipoService
from app.domain.errores import NoEncontrado, NombreDuplicado
from app.domain.puertos import Equipo


class FakeRepo:
    def __init__(self) -> None:
        self.equipos: dict[int, Equipo] = {}

    def crear(self, equipo: Equipo) -> Equipo:
        if any(e.nombre == equipo.nombre for e in self.equipos.values()):
            raise NombreDuplicado("Ya existe un equipo con ese nombre")
        nuevo = Equipo(equipo.nombre, equipo.es_admin, len(self.equipos) + 1)
        self.equipos[nuevo.id or 0] = nuevo
        return nuevo

    def obtener(self, id: int) -> Equipo | None:
        return self.equipos.get(id)


def test_crear_asigna_id():
    # Arrange
    servicio = EquipoService(FakeRepo())

    # Act
    e = servicio.crear("inventario", False)

    # Assert
    assert e == Equipo("inventario", False, 1)


def test_crear_duplicado_falla():
    # Arrange
    servicio = EquipoService(FakeRepo())
    servicio.crear("inventario", False)

    # Act / Assert
    with pytest.raises(NombreDuplicado):
        servicio.crear("inventario", True)


def test_obtener_existente():
    # Arrange
    servicio = EquipoService(FakeRepo())
    creado = servicio.crear("fabricacion", True)

    # Act
    e = servicio.obtener(creado.id or 0)

    # Assert
    assert e == creado


def test_obtener_inexistente_lanza_no_encontrado():
    # Arrange
    servicio = EquipoService(FakeRepo())

    # Act / Assert
    with pytest.raises(NoEncontrado, match="Equipo no encontrado"):
        servicio.obtener(999)

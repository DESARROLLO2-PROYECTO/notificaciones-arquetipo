import pytest
from pydantic import ValidationError

from app.security.schemas import EquipoIn, EquipoOut


@pytest.mark.parametrize("clave", ["esAdmin", "es_admin"])
def test_equipo_in_acepta_alias_y_nombre(clave):
    # Arrange / Act
    e = EquipoIn.model_validate({"nombre": "a", clave: True})

    # Assert
    assert e.es_admin is True


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"nombre": "", "esAdmin": False},
        {"nombre": "x" * 51, "esAdmin": False},
        {"nombre": "a", "esAdmin": "si"},
        {"nombre": "a\x00b", "esAdmin": False},
    ],
)
def test_equipo_in_rechaza_invalidos(cuerpo):
    # Act / Assert
    with pytest.raises(ValidationError):
        EquipoIn.model_validate(cuerpo)


def test_equipo_out_serializa_camel():
    # Arrange
    e = EquipoOut(id=1, nombre="a", es_admin=False)

    # Act / Assert
    assert e.model_dump(by_alias=True) == {"id": 1, "nombre": "a", "esAdmin": False}

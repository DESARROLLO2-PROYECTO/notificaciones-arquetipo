from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from app.domain.api_key_service import ApiKeyGenerada, LimiteLlavesActivas
from scripts import api_keys


@pytest.fixture
def servicio(monkeypatch):
    servicio = Mock()
    monkeypatch.setattr(api_keys, "ApiKeyService", lambda repo: servicio)

    @contextmanager
    def transaccion():
        yield Mock()

    monkeypatch.setattr(api_keys, "transaccion", transaccion)
    return servicio


def test_consola_revela_llave_solo_despues_del_commit(servicio, monkeypatch, capsys, caplog):
    llave = "secreto-de-prueba-no-es-una-credencial"
    servicio.generar.return_value = ApiKeyGenerada(7, "notificaciones", datetime.now(UTC), llave)
    confirmada = []

    @contextmanager
    def transaccion():
        yield Mock()
        assert capsys.readouterr().out == ""
        confirmada.append(True)

    monkeypatch.setattr(api_keys, "transaccion", transaccion)
    assert api_keys.main(["generar", "--rol", "notificaciones"]) == 0
    salida = capsys.readouterr()
    assert confirmada == [True]
    assert salida.out.count(llave) == 1
    assert "ID: 7" in salida.out
    assert "Rol: notificaciones" in salida.out
    assert salida.err == ""
    assert llave not in caplog.text


def test_fallo_del_commit_no_imprime_llave_ni_detalles(servicio, monkeypatch, capsys, caplog):
    llave = "secreto-de-prueba-no-es-una-credencial"
    servicio.generar.return_value = ApiKeyGenerada(7, "inventario", datetime.now(UTC), llave)

    @contextmanager
    def transaccion():
        yield Mock()
        raise RuntimeError(f"Error con datos sensibles: {llave}")

    monkeypatch.setattr(api_keys, "transaccion", transaccion)
    assert api_keys.main(["generar", "--rol", "inventario"]) == 1
    salida = capsys.readouterr()
    assert salida.out == ""
    assert "No fue posible administrar la API Key" in salida.err
    assert llave not in salida.err + caplog.text


def test_rol_invalido_sin_conexion(monkeypatch, capsys):
    conectar = Mock(side_effect=AssertionError("No debe conectar"))
    monkeypatch.setattr(api_keys, "transaccion", conectar)
    assert api_keys.main(["generar", "--rol", "admin"]) == 1
    assert capsys.readouterr().err == "Rol no válido\n"
    conectar.assert_not_called()


def test_limite_no_revela_ninguna_llave(servicio, capsys):
    servicio.generar.side_effect = LimiteLlavesActivas(
        "Ya existen dos llaves activas para este rol"
    )
    assert api_keys.main(["generar", "--rol", "inventario"]) == 1
    salida = capsys.readouterr()
    assert salida.out == ""
    assert salida.err == "Ya existen dos llaves activas para este rol\n"


def test_desactivar_por_id(servicio, capsys):
    assert api_keys.main(["desactivar", "--id", "7"]) == 0
    servicio.desactivar.assert_called_once_with(7)
    assert capsys.readouterr().out == "API Key desactivada correctamente\n"


@pytest.mark.parametrize("args", [[], ["desactivar", "--id", "0"], ["desactivar", "--id", "abc"]])
def test_argumentos_invalidos(args):
    with pytest.raises(SystemExit) as exc:
        api_keys.main(args)
    assert exc.value.code == 2


def test_listar_muestra_id_rol_prefijo_y_estado_sin_el_valor_de_la_llave(servicio, capsys):
    from app.domain.puertos import ResumenApiKey

    servicio.listar.return_value = [
        ResumenApiKey(1, "inventario", "89282489", True, datetime(2026, 11, 25, tzinfo=UTC)),
        ResumenApiKey(2, "fabricacion", "37c18a02", False, datetime(2026, 11, 25, tzinfo=UTC)),
    ]

    assert api_keys.main(["listar"]) == 0

    salida = capsys.readouterr().out
    assert "inventario" in salida and "89282489" in salida and "activa" in salida
    assert "inactiva" in salida and "fabricacion" in salida

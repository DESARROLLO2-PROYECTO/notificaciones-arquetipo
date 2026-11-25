import logging
import threading
import time
from pathlib import Path

import pytest

from scripts import planificador


class ServicioFalso:
    def __init__(self, resultados, parar: threading.Event | None = None, tras: int = 1):
        self._resultados = list(resultados)
        self.llamadas = 0
        self._parar, self._tras = parar, tras

    def ejecutar_ciclo(self):
        self.llamadas += 1
        if self._parar and self.llamadas >= self._tras:
            self._parar.set()
        resultado = self._resultados.pop(0)
        if isinstance(resultado, Exception):
            raise resultado
        return resultado


def test_un_ciclo_exitoso_se_registra_y_marca_el_latido(tmp_path: Path, caplog):
    latido = tmp_path / "latido"
    caplog.set_level(logging.INFO, logger="planificador")

    ok = planificador.un_ciclo(ServicioFalso([({"alertas": 2, "publicaciones": 1}, [])]), latido)

    assert ok is True and latido.exists()
    assert "Ciclo completado: alertas=2, publicaciones=1" in caplog.text


def test_un_ciclo_con_una_tarea_fallida_avisa_pero_sigue(tmp_path: Path, caplog):
    caplog.set_level(logging.INFO, logger="planificador")

    ok = planificador.un_ciclo(
        ServicioFalso([({"alertas": 1}, ["publicaciones"])]), tmp_path / "latido"
    )

    assert ok is False
    assert "tareas fallidas (publicaciones)" in caplog.text


def test_un_fallo_total_no_detiene_al_planificador(tmp_path: Path, caplog):
    latido = tmp_path / "latido"

    ok = planificador.un_ciclo(ServicioFalso([RuntimeError("base caída")]), latido)

    assert ok is False and not latido.exists()  # sin ciclo terminado, sin latido
    assert "Falló el ciclo completo" in caplog.text


def test_el_planificador_repite_y_descuenta_lo_que_tardó_cada_ciclo(tmp_path: Path):
    parar = threading.Event()
    servicio = ServicioFalso([({}, [])] * 3, parar, tras=3)
    esperas: list[float] = []
    horas = iter([0.0, 12.0, 100.0, 100.0, 200.0, 207.0])  # inicio y fin de cada ciclo
    parar.wait = lambda tiempo=None: esperas.append(tiempo) or parar.is_set()  # type: ignore[method-assign]

    planificador.ejecutar(servicio, 60, parar, tmp_path / "latido", reloj=lambda: next(horas))

    assert servicio.llamadas == 3
    assert esperas == [48.0, 60.0, 53.0]  # intervalo menos lo que tardó cada uno


def test_si_un_ciclo_tarda_mas_que_el_intervalo_no_espera_de_mas(tmp_path: Path):
    parar = threading.Event()
    servicio = ServicioFalso([({}, [])], parar, tras=1)
    esperas: list[float] = []
    horas = iter([0.0, 90.0])
    parar.wait = lambda tiempo=None: esperas.append(tiempo) or True  # type: ignore[method-assign]

    planificador.ejecutar(servicio, 60, parar, None, reloj=lambda: next(horas))

    assert esperas == [0.0]


def test_el_latido_reciente_marca_la_salud(tmp_path: Path):
    latido = tmp_path / "latido"

    assert planificador.latido_reciente(60, latido) is False  # nunca corrió
    latido.touch()
    assert planificador.latido_reciente(60, latido) is True
    assert planificador.latido_reciente(60, latido, ahora=time.time() + 3 * 60 + 31) is False


@pytest.fixture
def entorno(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x")
    monkeypatch.setenv("CICLO_INTERVALO_S", "20")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_verificar_usa_el_intervalo_configurado(entorno, monkeypatch, tmp_path: Path):
    latido = tmp_path / "latido"
    monkeypatch.setattr(planificador, "LATIDO", latido)
    monkeypatch.setattr(
        planificador,
        "latido_reciente",
        lambda intervalo, *a, **k: intervalo == 20 and latido.exists(),
    )

    assert planificador.main(["--verificar"]) == 1
    latido.touch()
    assert planificador.main(["--verificar"]) == 0


def test_una_vez_ejecuta_un_ciclo_y_devuelve_su_resultado(entorno, monkeypatch):
    from app.api import deps

    servicio = ServicioFalso([({"alertas": 1}, []), ({}, ["alertas"])])
    monkeypatch.setattr(deps, "get_servicio_notificaciones", lambda: servicio)

    assert planificador.main(["--una-vez"]) == 0
    assert planificador.main(["--una-vez"]) == 1
    assert servicio.llamadas == 2

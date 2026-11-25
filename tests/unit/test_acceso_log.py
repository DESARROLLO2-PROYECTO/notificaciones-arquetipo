import logging

from app.main import _OcultarQuery


def _registro(ruta: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.1:5000", "POST", ruta, "1.1", 401), None,
    )  # fmt: skip


def test_la_query_no_queda_en_el_log_de_acceso():
    registro = _registro("/notificaciones?api_key=llave-secreta&otro=1")

    assert _OcultarQuery().filter(registro) is True
    assert "llave-secreta" not in registro.getMessage()
    assert '"POST /notificaciones?<omitido> HTTP/1.1" 401' in registro.getMessage()


def test_una_ruta_sin_query_no_cambia():
    registro = _registro("/notificaciones/ciclo")

    _OcultarQuery().filter(registro)

    assert '"POST /notificaciones/ciclo HTTP/1.1" 401' in registro.getMessage()

from pathlib import Path

import httpx
import pytest

from scripts.demo import configuracion
from scripts.demo.principal import main
from scripts.demo.salida import Respuesta, Salida, _legible

LLAVES = {
    "DEMO_LLAVE_INVENTARIO": "li",
    "DEMO_LLAVE_FABRICACION": "lf",
    "DEMO_LLAVE_ADMIN": "la",
}


def test_la_direccion_se_cambia_con_un_argumento_o_una_variable(tmp_path: Path):
    por_defecto, _ = configuracion.cargar([], {}, tmp_path / "nada")
    por_variable, _ = configuracion.cargar(
        [], {"DEMO_URL": "http://10.0.0.7:8090/"}, tmp_path / "x"
    )
    por_argumento, _ = configuracion.cargar(
        ["--url", "http://192.168.1.50:8090"], {"DEMO_URL": "http://10.0.0.7:8090"}, tmp_path / "x"
    )

    assert por_defecto.url == "http://localhost:8090"
    assert por_variable.url == "http://10.0.0.7:8090"  # sin barra final
    assert por_argumento.url == "http://192.168.1.50:8090"  # el argumento manda


def test_las_llaves_salen_del_entorno_y_si_no_del_archivo(tmp_path: Path):
    archivo = tmp_path / ".demo.env"
    archivo.write_text("# comentario\nDEMO_LLAVE_INVENTARIO=del-archivo\nDEMO_LLAVE_ADMIN = adm\n")

    config, _ = configuracion.cargar([], {"DEMO_LLAVE_INVENTARIO": "del-entorno"}, archivo)

    assert config.llaves == {
        "inventario": "del-entorno",
        "fabricacion": "",
        "notificaciones": "adm",
    }


def test_las_opciones_de_presentacion(tmp_path: Path):
    config, preparar = configuracion.cargar(
        ["--rapido", "--sin-color", "--broker-caido", "--preparar", "--espera-reintento", "5"],
        {},
        tmp_path / "x",
    )

    assert (config.rapido, config.color, config.broker_caido, preparar) == (True, False, True, True)
    assert config.espera_reintento_s == 5


def test_no_color_en_el_entorno_apaga_los_colores(tmp_path: Path):
    config, _ = configuracion.cargar([], {"NO_COLOR": "1"}, tmp_path / "x")

    assert config.color is False


def test_los_cuerpos_se_muestran_como_pares_y_los_errores_por_campo():
    cuerpo = {
        "mensaje": "Datos inválidos",
        "errores": [{"campo": "stockActual", "error": "debe ser mayor o igual a 0"}],
    }

    assert _legible(cuerpo) == [
        "mensaje: Datos inválidos",
        "• stockActual: debe ser mayor o igual a 0",
    ]
    assert _legible({"a": 1, "b": "x"}) == ["a: 1  ·  b: x"]


def test_la_salida_marca_lo_esperado_y_lo_inesperado():
    lineas: list[str] = []
    salida = Salida(color=False, pausar=False, escribir=lineas.append)

    bien = salida.respuesta(Respuesta(201, {"id": "1"}, 12.0), 201, "Registrada")
    mal = salida.respuesta(Respuesta(500, None, 3.0), 201, "Registrada")

    assert (bien, mal) == (True, False)
    texto = "\n".join(lineas)
    assert "201 Created" in texto and "✓" in texto
    assert "✗ (se esperaba 201)" in texto


def test_el_resumen_falla_si_alguna_comprobacion_falla():
    lineas: list[str] = []
    salida = Salida(color=False, pausar=False, escribir=lineas.append)
    salida.registrar("Escena 1", "algo", True)
    salida.registrar("Escena 2", "otra cosa", False)

    assert salida.resumen() is False
    assert "1 de 2 comprobaciones fallaron" in "\n".join(lineas)


def test_sin_llaves_pide_prepararlas_y_no_llama_a_la_api(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    for variable in LLAVES:
        monkeypatch.delenv(variable, raising=False)
    lineas: list[str] = []

    codigo = main(["--rapido"], escribir=lineas.append)

    assert codigo == 2
    assert "--preparar" in "\n".join(lineas)


def test_si_la_api_no_responde_lo_dice_con_la_direccion(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    for variable, valor in LLAVES.items():
        monkeypatch.setenv(variable, valor)
    monkeypatch.delenv("AMQP_URL", raising=False)
    lineas: list[str] = []

    codigo = main(["--rapido", "--url", "http://127.0.0.1:1"], escribir=lineas.append)

    assert codigo == 2
    assert "No se pudo conectar a http://127.0.0.1:1" in "\n".join(lineas)


def test_preparar_sin_docker_explica_que_hacer(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "")
    lineas: list[str] = []

    codigo = main(["--preparar"], escribir=lineas.append)

    assert codigo == 2
    assert "DEMO_LLAVE_INVENTARIO" in "\n".join(lineas)


def test_si_health_no_responde_200_el_demo_se_detiene():
    def servidor(peticion: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    lineas: list[str] = []
    cliente = httpx.Client(base_url="http://x", transport=httpx.MockTransport(servidor))
    config, _ = configuracion.cargar(["--rapido"], LLAVES, Path("no-existe"))
    from scripts.demo.cola import Escucha
    from scripts.demo.principal import correr

    salida = Salida(color=False, pausar=False, escribir=lineas.append)

    assert correr(config, salida, cliente, Escucha(None)) is False
    assert "GET /health → 503" in "\n".join(lineas)


@pytest.mark.parametrize("ruta", ["/health"])
def test_el_cliente_mide_y_decodifica(ruta):
    from scripts.demo.equipos_falsos import ClienteApi

    cliente = ClienteApi(
        httpx.Client(
            base_url="http://x",
            transport=httpx.MockTransport(lambda p: httpx.Response(200, json={"status": "UP"})),
        )
    )

    r = cliente.enviar("GET", ruta, None)

    assert (r.estado, r.cuerpo) == (200, {"status": "UP"}) and r.ms >= 0


def _compose_falso(monkeypatch, respuestas: dict[str, str | None]):
    """Reemplaza `docker compose ...` por respuestas fijas según el subcomando."""

    def falso(raiz, *args):
        return respuestas.get(args[0])

    monkeypatch.setattr(configuracion, "_compose", falso)


def test_el_broker_de_la_api_local_se_traduce_a_localhost_con_el_puerto_publicado(
    monkeypatch, tmp_path: Path
):
    _compose_falso(
        monkeypatch,
        {"exec": "amqp://notif:cambiar_clave@rabbitmq:5672/", "port": "127.0.0.1:5673"},
    )

    assert configuracion.descubrir_amqp(tmp_path) == "amqp://notif:cambiar_clave@localhost:5673/"


def test_un_broker_externo_se_usa_tal_cual(monkeypatch, tmp_path: Path):
    _compose_falso(monkeypatch, {"exec": "amqps://u:p@lemur.cloudamqp.com/vh"})

    assert configuracion.descubrir_amqp(tmp_path) == "amqps://u:p@lemur.cloudamqp.com/vh"


@pytest.mark.parametrize(
    "respuestas",
    [{}, {"exec": "amqp://u:p@rabbitmq:5672/"}],  # sin API en el compose / puerto sin publicar
)
def test_si_no_se_puede_descubrir_no_hay_cola(monkeypatch, tmp_path: Path, respuestas):
    _compose_falso(monkeypatch, respuestas)

    assert configuracion.descubrir_amqp(tmp_path) is None


def test_compose_sin_docker_devuelve_none(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PATH", "")

    assert configuracion._compose(tmp_path, "ps") is None


def test_preparar_guarda_tambien_la_cola_para_mirarla(monkeypatch, tmp_path: Path):
    class Resultado:
        returncode = 0
        stdout = "API Key (se muestra una sola vez): " + "k" * 43
        stderr = ""

    monkeypatch.setattr(configuracion.subprocess, "run", lambda *a, **k: Resultado())
    monkeypatch.setattr(configuracion, "descubrir_amqp", lambda raiz: "amqp://u:p@localhost:5673/")
    archivo = tmp_path / ".demo.env"

    llaves = configuracion.preparar_llaves(tmp_path, archivo)

    assert set(llaves) == {"inventario", "fabricacion", "notificaciones"}
    guardado = configuracion.leer_archivo(archivo)
    assert guardado["AMQP_URL"] == "amqp://u:p@localhost:5673/"
    assert guardado["DEMO_LLAVE_ADMIN"] == "k" * 43


def test_en_local_el_demo_descubre_la_cola_si_no_hay_amqp_url(monkeypatch, tmp_path: Path):
    from scripts.demo import principal

    monkeypatch.chdir(tmp_path)
    for variable, valor in LLAVES.items():
        monkeypatch.setenv(variable, valor)
    monkeypatch.delenv("AMQP_URL", raising=False)
    consultas: list[Path] = []
    monkeypatch.setattr(principal, "descubrir_amqp", lambda raiz: consultas.append(raiz))

    principal.main(["--rapido", "--url", "http://127.0.0.1:1"], escribir=lambda _: None)
    principal.main(["--rapido", "--url", "http://192.168.1.50:1"], escribir=lambda _: None)

    assert consultas == [tmp_path]  # solo cuando apunta a la propia máquina

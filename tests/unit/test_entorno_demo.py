import runpy
import subprocess
from pathlib import Path

import pytest

from scripts.demo import criterios, entorno
from scripts.demo.entorno import DockerLocal


class Compose:
    """Reemplaza `docker compose ...`: devuelve respuestas fijas según el subcomando."""

    def __init__(self, respuestas: dict[str, tuple[int, str, str]] | None = None):
        self.respuestas = respuestas or {}
        self.llamadas: list[tuple[list[str], str | None]] = []

    def __call__(self, comando, **kwargs):
        self.llamadas.append((comando, kwargs.get("input")))
        subcomando = comando[2]
        codigo, salida, errores = self.respuestas.get(subcomando, (0, "", ""))
        return subprocess.CompletedProcess(comando, codigo, salida, errores)


@pytest.fixture
def compose(monkeypatch):
    falso = Compose({"ps": (0, "abc123\n", "")})
    monkeypatch.setattr(entorno.subprocess, "run", falso)
    monkeypatch.setattr(entorno.time, "sleep", lambda _: None)
    return falso


def test_disponible_si_el_servicio_api_esta_corriendo(compose, tmp_path: Path):
    assert DockerLocal(tmp_path).disponible is True
    assert compose.llamadas[0][0][:4] == ["docker", "compose", "ps", "-q"]


def test_no_disponible_sin_docker_o_sin_contenedor(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(entorno.subprocess, "run", Compose({"ps": (0, "", "")}))
    assert DockerLocal(tmp_path).disponible is False

    def sin_docker(*a, **k):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(entorno.subprocess, "run", sin_docker)
    assert DockerLocal(tmp_path).disponible is False


def test_cli_ejecuta_el_modulo_dentro_del_servicio(compose, tmp_path: Path):
    compose.respuestas["exec"] = (1, "salida", "Rol no válido")
    docker = DockerLocal(tmp_path)

    codigo, salida, errores = docker.cli("scripts.crear_api_key", "--rol", "marciano")

    assert (codigo, salida, errores) == (1, "salida", "Rol no válido")
    assert compose.llamadas[-1][0][2:] == [
        "exec", "-T", "api", "python", "-m", "scripts.crear_api_key", "--rol", "marciano",
    ]  # fmt: skip
    assert docker.texto_cli("scripts.listar_api_keys") == (
        "docker compose exec -T api python -m scripts.listar_api_keys"
    )


def test_sql_manda_la_consulta_por_stdin_y_separa_las_columnas(compose, tmp_path: Path):
    compose.respuestas["exec"] = (0, "inventario|2\nfabricacion|1\n", "")
    docker = DockerLocal(tmp_path)

    filas = docker.sql("select 1")

    assert filas == [["inventario", "2"], ["fabricacion", "1"]]
    comando, entrada = compose.llamadas[-1]
    assert entrada == "select 1" and "db" in comando


def test_sql_que_falla_lanza_un_error_claro(compose, tmp_path: Path):
    compose.respuestas["exec"] = (1, "", "ERROR: relation no existe")

    with pytest.raises(RuntimeError, match="La consulta falló"):
        DockerLocal(tmp_path).sql("select * from nada")


def test_registros_junta_la_salida_y_los_errores(compose, tmp_path: Path):
    compose.respuestas["logs"] = (0, "uno\n", "dos\n")

    assert DockerLocal(tmp_path).registros() == "uno\ndos\n"


def test_apagar_y_encender_la_base_espera_a_que_responda(compose, tmp_path: Path, monkeypatch):
    docker = DockerLocal(tmp_path)
    intentos = iter([RuntimeError("aún no"), [["1"]]])

    def sql(consulta):
        resultado = next(intentos)
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    monkeypatch.setattr(docker, "sql", sql)

    assert docker.parar_bd() is True
    assert docker.iniciar_bd() is True


def test_si_la_base_no_vuelve_iniciar_devuelve_falso(compose, tmp_path: Path, monkeypatch):
    docker = DockerLocal(tmp_path)
    monkeypatch.setattr(docker, "sql", lambda c: (_ for _ in ()).throw(RuntimeError("no")))

    assert docker.iniciar_bd() is False

    compose.respuestas["start"] = (1, "", "")
    assert docker.iniciar_bd() is False


def _con_llaves(monkeypatch):
    for variable in ("DEMO_LLAVE_INVENTARIO", "DEMO_LLAVE_FABRICACION", "DEMO_LLAVE_ADMIN"):
        monkeypatch.setenv(variable, "llave")


def test_sin_llaves_la_demo_por_criterios_pide_prepararlas(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    for variable in ("DEMO_LLAVE_INVENTARIO", "DEMO_LLAVE_FABRICACION", "DEMO_LLAVE_ADMIN"):
        monkeypatch.delenv(variable, raising=False)
    lineas: list[str] = []

    codigo = criterios.main(["--hu", "01"], escribir=lineas.append)

    assert codigo == 2 and "--preparar" in "\n".join(lineas)


def test_si_la_api_no_responde_la_demo_por_criterios_lo_dice(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    _con_llaves(monkeypatch)
    lineas: list[str] = []

    codigo = criterios.main(
        ["--hu", "01", "--rapido", "--url", "http://127.0.0.1:1"], escribir=lineas.append
    )

    assert codigo == 2 and "No se pudo conectar a http://127.0.0.1:1" in "\n".join(lineas)


def test_preparar_sin_docker_en_la_demo_por_criterios(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "")
    lineas: list[str] = []

    assert criterios.main(["--hu", "11", "--preparar"], escribir=lineas.append) == 2


def test_hu_11_sin_el_compose_local_explica_que_falta(monkeypatch, tmp_path: Path):
    import httpx

    class SinDocker:
        disponible = False

    monkeypatch.chdir(tmp_path)
    _con_llaves(monkeypatch)
    cliente = httpx.Client(
        base_url="http://x", transport=httpx.MockTransport(lambda p: httpx.Response(200, json={}))
    )
    lineas: list[str] = []

    codigo = criterios.main(
        ["--hu", "11", "--rapido", "--sin-color", "--url", "http://x"],
        http=cliente, entorno=SinDocker(), escribir=lineas.append,
    )  # fmt: skip

    salida = "\n".join(lineas)
    assert codigo == 1 and "necesita el docker compose local" in salida


@pytest.mark.parametrize(
    ("modulo", "objetivo"),
    [
        ("scripts.listar_api_keys", "scripts.api_keys.main"),
        ("scripts.demo", "scripts.demo.principal.main"),
    ],
)
def test_los_puntos_de_entrada_llaman_a_su_main(monkeypatch, modulo, objetivo):
    monkeypatch.setattr(objetivo, lambda *a, **k: 0)

    with pytest.raises(SystemExit) as salida:
        runpy.run_module(modulo, run_name="__main__")

    assert salida.value.code == 0

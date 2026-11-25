"""Guardas del contrato OpenAPI: se rompen si un endpoint nuevo no sigue las convenciones."""

import json

import pytest
from openapi_spec_validator import validate

from scripts import exportar_openapi

_PUBLICOS = {"/health"}
_METODOS = {"get", "post", "put", "patch", "delete"}


@pytest.fixture(scope="module")
def contrato() -> dict:
    return json.loads(exportar_openapi.generar())


def _operaciones(contrato):
    for ruta, operaciones in contrato["paths"].items():
        for metodo, operacion in operaciones.items():
            if metodo in _METODOS:
                yield ruta, metodo, operacion


def test_el_contrato_es_openapi_valido(contrato):
    validate(contrato)


def test_el_archivo_publicado_esta_al_dia():
    publicado = exportar_openapi.RUTA.read_text(encoding="utf-8")

    assert publicado == exportar_openapi.generar(), (
        "docs/api/openapi.json está desactualizado: ejecute "
        "`uv run python -m scripts.exportar_openapi`"
    )


def test_el_contrato_tiene_informacion_para_otros_equipos(contrato):
    assert contrato["info"]["description"]
    assert contrato["info"]["contact"]["name"]
    assert contrato["servers"]
    assert {t["name"] for t in contrato["tags"]} >= {"notificaciones", "administración", "health"}


def test_cada_operacion_esta_documentada_y_etiquetada(contrato):
    etiquetas = {t["name"] for t in contrato["tags"]}
    for ruta, metodo, operacion in _operaciones(contrato):
        donde = f"{metodo.upper()} {ruta}"
        assert operacion.get("summary"), f"{donde}: falta summary"
        assert operacion.get("description"), f"{donde}: falta description"
        assert operacion.get("tags") and set(operacion["tags"]) <= etiquetas, f"{donde}: etiquetas"


def test_los_ids_de_operacion_son_unicos_y_legibles(contrato):
    ids = [operacion["operationId"] for _, _, operacion in _operaciones(contrato)]

    assert len(ids) == len(set(ids))
    assert all("_" not in id and id[0].islower() for id in ids), ids
    # Un verbo suelto ("crear") no dice sobre qué recurso actúa: debe ser verbo + recurso
    assert all(any(c.isupper() for c in id) or id == "health" for id in ids), ids


def test_toda_ruta_privada_declara_la_llave_y_sus_errores(contrato):
    for ruta, metodo, operacion in _operaciones(contrato):
        if ruta in _PUBLICOS:
            assert "security" not in operacion
            continue
        donde = f"{metodo.upper()} {ruta}"
        assert operacion.get("security"), f"{donde}: sin X-API-Key"
        respuestas = operacion["responses"]
        assert {"401", "500"} <= set(respuestas), f"{donde}: faltan 401 o 500"
        for codigo in ("401", "403", "500"):
            if codigo in respuestas:
                esquema = respuestas[codigo]["content"]["application/json"]["schema"]
                assert esquema["$ref"].endswith("/ErrorResponse"), f"{donde}: {codigo}"
        if "requestBody" in operacion:
            assert "422" in respuestas, f"{donde}: falta 422"
            esquema = respuestas["422"]["content"]["application/json"]["schema"]
            assert esquema["$ref"].endswith("/ErrorValidacionResponse")


def test_los_cuerpos_de_entrada_traen_ejemplos_y_campos_descritos(contrato):
    entradas = {n: e for n, e in contrato["components"]["schemas"].items() if n.endswith("Request")}

    assert {"CrearNotificacionRequest", "CondicionUrgenteRequest"} <= set(entradas)
    for nombre, entrada in entradas.items():
        assert len(entrada.get("examples", [])) >= 2, f"{nombre}: faltan ejemplos"
        sin_descripcion = [c for c, v in entrada["properties"].items() if not v.get("description")]
        assert not sin_descripcion, f"{nombre}: campos sin descripción {sin_descripcion}"


def test_la_llave_se_declara_como_header_x_api_key(contrato):
    esquemas = contrato["components"]["securitySchemes"]

    assert list(esquemas.values()) == [{"type": "apiKey", "in": "header", "name": "X-API-Key"}]


def test_el_webhook_documenta_la_firma_para_el_receptor(contrato):
    operacion = contrato["webhooks"]["notificacion"]["post"]
    cabeceras = {p["name"] for p in operacion["parameters"] if p["in"] == "header"}

    assert cabeceras == {"X-Notification-Id", "X-Timestamp", "X-Signature"}
    assert "HMAC" in operacion["description"]
    cuerpo = contrato["components"]["schemas"]["NotificacionEntregada"]
    assert {
        "id",
        "tipo",
        "equipoEmisor",
        "equipoDestino",
        "fechaRegistro",
        "mensaje",
        "datos",
    } == set(cuerpo["properties"])

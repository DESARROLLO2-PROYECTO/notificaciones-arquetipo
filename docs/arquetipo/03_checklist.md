# Fase 2, paso 2.3: Archetype Self-Validation Checklist

Comandos de verificación (locales, sin CI):

```bash
uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy app \
  && uv run pytest --cov=app \
  && uv run coverage report --include='app/domain/*,app/security/*' --fail-under=100 \
  && docker build -q .
```

| Ítem | Estado | Evidencia |
|---|---|---|
| C01 Cada capa del DAS tiene su paquete | ✅ PASS | `app/api`, `app/domain`, `app/infrastructure`, `app/security`, `migrations/` |
| C02 Cada patrón de la Fase 1 está implementado y anotado | ⚠️ PARTIAL | Implementados: multicapa, Controlador, Service, Repository, DTO/Validator (`security/schemas.py`), Health check (`api/health.py`), Unit of Work, inyección de dependencias. Pendientes por depender de una HU: API Key, Worker, Scheduler, Publisher, Mailer |
| C03 Flujo transaccional conectado de punta a punta | ✅ PASS | `POST /equipos` → `EquipoService.crear` → `EquipoRepo` → PostgreSQL → 201; `GET /equipos/{id}` lo lee |
| C04 Cada método público de domain tiene test | ✅ PASS | `tests/unit/`, 100 % en `app/domain` y `app/security` |
| C05 Cobertura configurada y comando en el README | ⚠️ PARTIAL | `fail_under = 80` global en `pyproject.toml`; el 100 % de domain y security es un comando manual (README §5), sin CI que lo exija |
| C06 `docker compose up --build` arranca limpio | ✅ PASS | db y api healthy, `/health` → `{"status":"UP"}` y los curl de POST/GET responden como se espera |
| C07 Sin secretos ni valores hardcodeados | ✅ PASS | Todo sale de `.env` o `pydantic-settings` |
| C08 `.env.example` documenta cada variable | ✅ PASS | Cada variable con comentario y placeholder |
| C09 Dockerfile multi-stage y sin root | ✅ PASS | builder (uv) y runtime `python:3.12.16-slim-bookworm`, uid 10001; sin `latest` |
| C10 README con comandos exactos | ✅ PASS | §3 quick start, §4 tests, §5 cobertura |
| C11 Nada contradice al DAS | ✅ PASS | Capas del diagrama lógico; 409 por nombre duplicado es [Archetype Convention Addition] (UNIQUE del ER) |
| C12 Los ⚠️ de la Fase 1 están resueltos o documentados | ✅ PASS | C2, C6 y C8 resueltos en el código; C1, C3, C4, C5 y C7 documentados como limitaciones o siguientes pasos en README §8 (detalle al final de los concerns en `01_validacion.md`) |

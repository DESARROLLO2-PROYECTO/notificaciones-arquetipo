from fastapi import APIRouter

router = APIRouter()


@router.get(
    "/health",
    tags=["health"],
    summary="Estado del proceso",
    description='Responde `{"status": "UP"}` si el proceso está vivo. No consulta la base.',
)
def health() -> dict[str, str]:
    """Proceso vivo. No toca la BD: de eso se encarga el healthcheck de db en compose."""
    return {"status": "UP"}

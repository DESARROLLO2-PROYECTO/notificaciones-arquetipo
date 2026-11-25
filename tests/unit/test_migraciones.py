from alembic.config import Config
from alembic.script import ScriptDirectory


def test_las_migraciones_tienen_una_sola_cabeza():
    """Dos ramas que migran a la vez dejan dos cabezas y `alembic upgrade head` falla.

    Quien mergee segundo debe cambiar el `down_revision` de su migración a la cabeza actual.
    """
    cabezas = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()

    assert len(cabezas) == 1, f"Cabezas de Alembic: {cabezas}"

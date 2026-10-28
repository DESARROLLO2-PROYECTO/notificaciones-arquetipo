"""Validator / DTO (Pydantic v2). JSON en camelCase."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool
from pydantic.alias_generators import to_camel


class _Base(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class EquipoIn(_Base):
    nombre: Annotated[str, Field(min_length=1, max_length=50, pattern=r"^[^\x00]+$")]
    es_admin: StrictBool


class EquipoOut(_Base):
    id: int
    nombre: str
    es_admin: bool

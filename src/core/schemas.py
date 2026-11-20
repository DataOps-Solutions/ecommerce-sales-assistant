"""Contrato de salida del asistente (Pydantic v2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.tools.store_tools import SKU_RE

Intent = Literal[
    "product_discovery",
    "order_tracking",
    "shipping_policy",
    "human_handoff",
    "blocked",
]

MAX_REPLY_CHARS = 1200
MAX_RECOMMENDED = 5


class AssistantTurn(BaseModel):
    """Respuesta estructurada de un turno. Campos extra están prohibidos."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reply: str = Field(min_length=1, max_length=MAX_REPLY_CHARS)
    intent: Intent
    recommended_skus: list[str] = Field(default_factory=list, max_length=MAX_RECOMMENDED)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_human: bool

    @field_validator("recommended_skus")
    @classmethod
    def _check_sku_format(cls, value: list[str]) -> list[str]:
        for sku in value:
            if not SKU_RE.match(sku):
                raise ValueError(f"SKU con formato inválido: {sku!r}")
        if len(set(value)) != len(value):
            raise ValueError("SKUs recomendados duplicados")
        return value

    @model_validator(mode="after")
    def _blocked_has_no_skus(self) -> "AssistantTurn":
        if self.intent == "blocked" and self.recommended_skus:
            raise ValueError("un turno bloqueado no puede recomendar SKUs")
        return self

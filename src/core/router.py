"""Router determinista: decide intención y herramientas a llamar.

No usa LLM. Extrae email, número de pedido, SKU y tope de precio con reglas, y
completa datos faltantes desde el contexto de la sesión.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.core.schemas import Intent
from src.tools.store_tools import EMAIL_RE, normalize_text

EMAIL_FIND_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ORDER_FIND_RE = re.compile(r"\bORD-\d{4,}\b", re.IGNORECASE)
SKU_FIND_RE = re.compile(r"\b[A-Za-z]{3}-\d{3}\b")
MAX_PRICE_RE = re.compile(
    r"(menos de|hasta|maximo|max|tope|no mas de|no más de|por debajo de)\s*\$?\s*(\d[\d.]*)"
)

HANDOFF_RE = re.compile(
    r"\b(humano|persona real|hablar con (una |un )?(persona|agente|asesor)|agente|gerente|"
    r"supervisor|reclamo|reembolso|devolucion|abogado|denuncia)\b"
)
ORDER_RE = re.compile(r"\b(pedido|orden|seguimiento|rastreo|tracking|donde esta|llega|llego|estado)\b")
SHIPPING_RE = re.compile(r"\b(envio|envios|entrega|tarda|demora|politica|costo de envio|gratis)\b")
PRODUCT_HINT_RE = re.compile(r"\b(busco|quiero|tenes|tienen|hay|precio|cuesta|cuanto|stock|producto|cargador|auricular|cable|parlante|mouse|teclado|ssd|pendrive|camara)\b")


@dataclass(frozen=True)
class RoutePlan:
    intent: Intent | None
    query: str = ""
    max_price: float | None = None
    sku: str | None = None
    order_id: str | None = None
    email: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "query": self.query,
            "max_price": self.max_price,
            "sku": self.sku,
            "order_id": self.order_id,
            "has_email": self.email is not None,
        }


def extract_email(text: str) -> str | None:
    for candidate in EMAIL_FIND_RE.findall(text):
        if EMAIL_RE.match(candidate):
            return candidate
    return None


def extract_order_id(text: str) -> str | None:
    match = ORDER_FIND_RE.search(text)
    return match.group(0).upper() if match else None


def extract_sku(text: str) -> str | None:
    match = SKU_FIND_RE.search(text)
    return match.group(0).upper() if match else None


def extract_max_price(text: str) -> float | None:
    match = MAX_PRICE_RE.search(normalize_text(text))
    if not match:
        return None
    digits = match.group(2).replace(".", "")
    return float(digits) if digits.isdigit() else None


def _query_text(text: str) -> str:
    """Texto sin emails, IDs ni cifras de precio, para buscar en catálogo."""
    cleaned = EMAIL_FIND_RE.sub(" ", text)
    cleaned = ORDER_FIND_RE.sub(" ", cleaned)
    cleaned = MAX_PRICE_RE.sub(" ", normalize_text(cleaned))
    return cleaned


def route(message: str, context: dict[str, Any] | None = None) -> RoutePlan:
    context = context or {}
    normalized = normalize_text(message)

    email = extract_email(message) or context.get("email")
    order_id = extract_order_id(message) or context.get("order_id")
    sku = extract_sku(message)
    max_price = extract_max_price(message)

    if HANDOFF_RE.search(normalized):
        intent: Intent | None = "human_handoff"
    elif ORDER_RE.search(normalized) or extract_order_id(message):
        intent = "order_tracking"
    elif SHIPPING_RE.search(normalized):
        intent = "shipping_policy"
    elif PRODUCT_HINT_RE.search(normalized) or sku:
        intent = "product_discovery"
    else:
        intent = None

    # Se usa el email/pedido de la sesión solo para consultas de pedido.
    if intent != "order_tracking":
        email = extract_email(message)
        order_id = extract_order_id(message)

    query = _query_text(message) if intent == "product_discovery" else ""
    return RoutePlan(
        intent=intent,
        query=query,
        max_price=max_price,
        sku=sku,
        order_id=order_id,
        email=email,
    )

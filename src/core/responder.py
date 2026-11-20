"""Ejecución de herramientas y respuesta determinista (modo offline).

Este módulo es la fuente de verdad del turno: el LLM, si existe, solo redacta
sobre estos mismos datos y sus SKUs se validan contra `tool_calls` de este turno.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.router import RoutePlan
from src.core.schemas import AssistantTurn
from src.core.guardrails import blocked_reply
from src.tools.store_tools import check_order_status, get_product_by_sku, search_catalog

MAX_LISTED_PRODUCTS = 3
ORDER_STATUS_ES = {
    "preparing": "en preparación",
    "shipped": "despachado",
    "delivered": "entregado",
    "delayed": "demorado",
}


@dataclass
class ToolResults:
    products: list[dict[str, Any]] = field(default_factory=list)
    product: dict[str, Any] | None = None
    order: dict[str, Any] | None = None
    order_checked: bool = False
    order_reason: str | None = None
    tool_calls: list[str] = field(default_factory=list)

    @property
    def grounded_skus(self) -> set[str]:
        skus = {p["sku"] for p in self.products}
        if self.product:
            skus.add(self.product["sku"])
        return skus


def execute_plan(plan: RoutePlan) -> ToolResults:
    """Llama a las herramientas que correspondan al plan. Sin LLM, sin red."""
    results = ToolResults()
    if plan.intent == "product_discovery":
        if plan.sku:
            results.tool_calls.append("get_product_by_sku")
            results.product = get_product_by_sku(plan.sku)
        if plan.query:
            results.tool_calls.append("search_catalog")
            results.products = search_catalog(plan.query, max_price=plan.max_price)
    elif plan.intent == "order_tracking" and plan.order_id and plan.email:
        results.tool_calls.append("check_order_status")
        results.order_checked = True
        lookup = check_order_status(plan.order_id, plan.email)
        if lookup.get("found"):
            results.order = lookup
        else:
            results.order_reason = lookup.get("reason")
    return results


def _money(value: float) -> str:
    return f"${value:,.0f}".replace(",", ".")


def blocked_turn(category: str | None) -> AssistantTurn:
    return AssistantTurn(
        reply=blocked_reply(category),
        intent="blocked",
        recommended_skus=[],
        confidence=1.0,
        requires_human=False,
    )


HANDOFF_REPLY = (
    "Te derivo con un agente humano del equipo de atención. Te van a contactar a la brevedad."
)


def handoff_turn(reply: str = HANDOFF_REPLY, confidence: float = 0.95) -> AssistantTurn:
    """Derivación a humano. Por defecto es una solicitud explícita del cliente."""
    return AssistantTurn(
        reply=reply,
        intent="human_handoff",
        recommended_skus=[],
        confidence=confidence,
        requires_human=True,
    )


def _product_turn(plan: RoutePlan, results: ToolResults, threshold: float) -> AssistantTurn:
    if plan.sku and results.product is None and not plan.query:
        return AssistantTurn(
            reply=f"No encontré el SKU {plan.sku} en el catálogo. Podés buscarlo por nombre o categoría.",
            intent="product_discovery",
            recommended_skus=[],
            confidence=0.6,
            requires_human=False,
        )

    products = list(results.products)
    if results.product and results.product["sku"] not in {p["sku"] for p in products}:
        products.insert(0, results.product)

    if not products:
        filter_text = f" con precio hasta {_money(plan.max_price)} ARS" if plan.max_price else ""
        return AssistantTurn(
            reply=(
                f"No encontré productos para '{plan.query}'{filter_text}. "
                "Probá con otra palabra clave o ampliá el precio máximo."
            ),
            intent="product_discovery",
            recommended_skus=[],
            confidence=0.5,
            requires_human=False,
        )

    lines = []
    recommended: list[str] = []
    for product in products[:MAX_LISTED_PRODUCTS]:
        stock_text = f"en stock ({product['stock']} u.)" if product["in_stock"] else "sin stock"
        line = (
            f"- {product['name']} ({product['sku']}): {_money(product['price_ars'])} ARS, "
            f"{stock_text}, envío en {product['shipping_days']} día(s)"
        )
        if product["price_ars"] >= threshold:
            line += f". Envío gratis (compras desde {_money(threshold)} ARS)"
        lines.append(line + ".")
        if product["in_stock"]:
            recommended.append(product["sku"])

    if recommended:
        reply = "Encontré estas opciones:\n" + "\n".join(lines)
        confidence = 0.9
    else:
        reply = "Encontré coincidencias, pero no hay stock disponible en este momento:\n" + "\n".join(lines)
        confidence = 0.7

    return AssistantTurn(
        reply=reply,
        intent="product_discovery",
        recommended_skus=recommended,
        confidence=confidence,
        requires_human=False,
    )


def _order_turn(plan: RoutePlan, results: ToolResults) -> AssistantTurn:
    if not plan.order_id and not plan.email:
        text = (
            "Para consultar tu pedido necesito el número (formato ORD-1001) "
            "y el email con el que hiciste la compra."
        )
    elif not plan.order_id:
        text = "Indicame el número de pedido (formato ORD-1001) para verificarlo."
    elif not plan.email:
        text = f"Necesito el email con el que hiciste la compra para verificar el pedido {plan.order_id}."
    elif results.order is None:
        text = "No encontré un pedido con ese número y email. Revisá los datos e intentá de nuevo."
        return AssistantTurn(
            reply=text,
            intent="order_tracking",
            recommended_skus=[],
            confidence=0.8,
            requires_human=False,
        )
    else:
        order = results.order
        status = ORDER_STATUS_ES.get(order["status"], order["status"])
        parts = [f"Tu pedido {order['order_id']} está {status}."]
        if order["tracking_code"]:
            parts.append(f"Código de seguimiento: {order['tracking_code']}.")
        else:
            parts.append("Todavía no tiene código de seguimiento.")
        if order["status"] == "delayed":
            parts.append("Tiene una demora; te derivo con un agente para hacer seguimiento.")
        elif order["eta_days"] > 0:
            parts.append(f"Llegada estimada en {order['eta_days']} día(s).")
        else:
            parts.append("Figura como entregado.")
        return AssistantTurn(
            reply=" ".join(parts),
            intent="order_tracking",
            recommended_skus=[],
            confidence=0.9,
            requires_human=False,
        )

    return AssistantTurn(
        reply=text,
        intent="order_tracking",
        recommended_skus=[],
        confidence=0.7,
        requires_human=False,
    )


def compose_offline(plan: RoutePlan, results: ToolResults, threshold: float) -> AssistantTurn:
    """Compone el turno sin LLM a partir del plan y las herramientas ejecutadas."""
    if plan.intent == "human_handoff":
        return handoff_turn()

    if plan.intent == "order_tracking":
        return _order_turn(plan, results)

    if plan.intent == "shipping_policy":
        return AssistantTurn(
            reply=(
                f"El envío es gratis en compras desde {_money(threshold)} ARS. "
                "Para compras menores, el costo y el plazo dependen del producto; "
                "lo ves en la ficha de cada uno. No ofrecemos descuentos fuera de los precios publicados."
            ),
            intent="shipping_policy",
            recommended_skus=[],
            confidence=0.9,
            requires_human=False,
        )

    if plan.intent == "product_discovery":
        if plan.query or plan.sku:
            return _product_turn(plan, results, threshold)

    # Sin intención clara: pedir aclaración con confianza baja (escala por umbral).
    return AssistantTurn(
        reply=(
            "¿Podrías contarme qué necesitás? Puedo buscar productos, consultar un pedido "
            "o explicarte la política de envíos."
        ),
        intent="product_discovery",
        recommended_skus=[],
        confidence=0.3,
        requires_human=False,
    )

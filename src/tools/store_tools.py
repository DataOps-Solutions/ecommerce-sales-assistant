"""Herramientas deterministas de la tienda.

Todas las funciones leen datos sintéticos de `data_seed/` y no usan red ni
aleatoriedad: la misma entrada siempre produce la misma salida.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

SEED_DIR = Path(__file__).resolve().parents[2] / "data_seed"

SKU_RE = re.compile(r"^[A-Z]{3}-\d{3}$")
ORDER_ID_RE = re.compile(r"^ORD-\d{4,}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

STOPWORDS = frozenset(
    {
        "a", "al", "algo", "busco", "con", "de", "del", "el", "en", "es", "hay",
        "la", "las", "los", "me", "mi", "necesito", "o", "para", "por", "quiero",
        "que", "tenes", "tienen", "tienes", "un", "una", "y", "precio", "menos",
        "hasta", "barato", "barata", "producto", "productos",
    }
)


def normalize_text(text: str) -> str:
    """Minúsculas, sin acentos, espacios colapsados."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict[str, Any], ...]:
    with (SEED_DIR / "catalog.json").open(encoding="utf-8") as fh:
        return tuple(json.load(fh))


@lru_cache(maxsize=1)
def _orders() -> tuple[dict[str, Any], ...]:
    with (SEED_DIR / "orders.json").open(encoding="utf-8") as fh:
        return tuple(json.load(fh))


def catalog_skus() -> frozenset[str]:
    """Conjunto de SKUs válidos del catálogo (fuente para validar salidas)."""
    return frozenset(p["sku"] for p in _catalog())


def _public_product(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "sku": product["sku"],
        "name": product["name"],
        "category": product["category"],
        "price_ars": product["price_ars"],
        "stock": product["stock"],
        "in_stock": product["stock"] > 0,
        "specs": dict(product["specs"]),
        "shipping_days": product["shipping_days"],
    }


def _query_terms(query: str) -> list[str]:
    terms = []
    for raw in re.split(r"[^a-z0-9]+", normalize_text(query)):
        if len(raw) < 3 or raw in STOPWORDS:
            continue
        # Stem simple: "cargadores" y "cargador" comparten prefijo de 5 letras.
        terms.append(raw[:5] if len(raw) > 5 else raw)
    return terms


def _haystack(product: dict[str, Any]) -> str:
    parts = [product["sku"], product["name"], product["category"]]
    parts += [str(v) for v in product["specs"].values()]
    return normalize_text(" ".join(parts))


def search_catalog(
    query: str,
    max_price: float | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Busca productos por palabras clave, con tope de precio opcional.

    Orden: más coincidencias primero, luego precio ascendente y SKU.
    Una consulta sin términos útiles devuelve lista vacía (no inventa resultados).
    """
    if max_price is not None and (
        isinstance(max_price, bool) or not isinstance(max_price, (int, float)) or max_price < 0
    ):
        raise ValueError("max_price debe ser un número >= 0")

    terms = _query_terms(query or "")
    if not terms:
        return []

    scored: list[tuple[int, dict[str, Any]]] = []
    for product in _catalog():
        if max_price is not None and product["price_ars"] > max_price:
            continue
        haystack = _haystack(product)
        score = sum(1 for term in terms if term in haystack)
        if score > 0:
            scored.append((score, product))

    scored.sort(key=lambda item: (-item[0], item[1]["price_ars"], item[1]["sku"]))
    return [_public_product(p) for _, p in scored[:limit]]


def get_product_by_sku(sku: str) -> dict[str, Any] | None:
    """Devuelve el producto con ese SKU exacto o None si no existe."""
    normalized = (sku or "").strip().upper()
    if not SKU_RE.match(normalized):
        return None
    for product in _catalog():
        if product["sku"] == normalized:
            return _public_product(product)
    return None


def check_order_status(order_id: str, email: str) -> dict[str, Any]:
    """Consulta el estado de un pedido. Exige email exacto del cliente.

    Pedido inexistente y email incorrecto devuelven la misma respuesta
    (`not_found`) para no permitir enumerar pedidos ajenos.
    Nunca devuelve datos personales (ni el email).
    """
    normalized_email = (email or "").strip().lower()
    if not EMAIL_RE.match(normalized_email):
        return {"found": False, "reason": "invalid_email"}

    normalized_id = (order_id or "").strip().upper()
    if not ORDER_ID_RE.match(normalized_id):
        return {"found": False, "reason": "not_found"}

    for order in _orders():
        if order["order_id"] == normalized_id and order["customer_email"].lower() == normalized_email:
            return {
                "found": True,
                "order_id": order["order_id"],
                "status": order["status"],
                "tracking_code": order["tracking_code"],
                "eta_days": order["eta_days"],
            }
    return {"found": False, "reason": "not_found"}

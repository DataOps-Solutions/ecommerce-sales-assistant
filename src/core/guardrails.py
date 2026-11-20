"""Guardrails de entrada (antes del LLM) y de salida (antes de responder).

Entrada: bloquea prompt injection, manipulación de precios/descuentos y
pedidos de datos de otros clientes. Se evalúa sobre texto normalizado
(minúsculas, sin acentos).

Salida: verifica que los SKUs existan en el catálogo, que no se prometan
descuentos fuera de política y que el envío gratis esté condicionado al umbral.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.core.schemas import AssistantTurn
from src.tools.store_tools import normalize_text

MAX_INPUT_CHARS = 1000

# (categoría, patrón) sobre texto normalizado.
INPUT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("prompt_injection", re.compile(
        r"ignor\w*\s+(todas?\s+)?(las\s+|tus\s+|mis\s+)?"
        r"(instrucciones|reglas|indicaciones|mensajes anteriores)")),
    ("prompt_injection", re.compile(r"ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+(instructions|rules|messages)")),
    ("prompt_injection", re.compile(
        r"(revela|muestra|imprime|dime|repite|escribe)\s+(tu\s+|el\s+|tus\s+)?"
        r"(system\s+prompt|prompt del sistema|prompt de sistema|instrucciones de sistema|prompt)")),
    ("prompt_injection", re.compile(r"\bsystem\s+prompt\b")),
    ("prompt_injection", re.compile(r"\bjailbreak\b")),
    ("prompt_injection", re.compile(r"\b(modo|mode)\s+(desarrollador|developer|dan|sin restricciones)\b")),
    ("prompt_injection", re.compile(
        r"\b(actua como|act as|pretend to be|finge ser|ahora eres|eres ahora)\s+"
        r"(un |una |el |la )?(administrador|admin|desarrollador|developer|root|superusuario)")),
    ("prompt_injection", re.compile(r"\bolvida\w*\s+(tus|las)\s+(reglas|instrucciones)")),
    ("price_manipulation", re.compile(
        r"\b(cambi|modifi|ajust|estableci|fij)\w*\s+(el\s+|los\s+|un\s+|mi\s+)?precio")),
    ("price_manipulation", re.compile(r"\bpon\w*\s+(el\s+|un\s+|mi\s+)?precio\b")),
    ("price_manipulation", re.compile(r"\b(a|en)\s+(1|un|uno|cero|0)\s*(peso|pesos|ars|\$)")),
    ("price_manipulation", re.compile(
        r"\b(cobr|vend|factur)\w*\b.{0,30}\b(1|un|uno|cero|0)\s*(peso|pesos|ars|\$)")),
    ("price_manipulation", re.compile(
        r"\b(descuento|rebaja|cupon|promo|oferta)\w*\b.{0,40}"
        r"(\d{1,3}\s?%|100|gratis|gratuit\w*|sin costo|el total)")),
    ("price_manipulation", re.compile(r"\b(aplic\w*|activ\w*|carg\w*|us\w*)\s+(el\s+|este\s+|un\s+)?(cupon|codigo|descuento)\b")),
    ("price_manipulation", re.compile(r"\bcupon\s+(admin|interno|staff|empleado|secreto|maestro)\b")),
    ("price_manipulation", re.compile(r"\bsin pagar\b")),
    ("price_manipulation", re.compile(
        r"\b(dame|dej\w*|regal\w*)\b.{0,30}\b(gratis|gratuit\w*|sin costo)\b")),
    ("customer_data", re.compile(
        r"\b(pedidos?|ordenes|compras|datos|email|mail|direccion|telefono|dni)\b.{0,30}"
        r"\b(de|del)\s+(otro|otra|otros|otras|este cliente|ese cliente|un cliente|cualquier)")),
    ("customer_data", re.compile(
        r"\b(pedidos?|ordenes|compras)\s+(de|del)\s+(mi|mis)\s+(vecin|amig|ex|pareja|jefe|socio|hermano|hermana|madre|padre)")),
    ("customer_data", re.compile(
        r"\b(lista|listado|todos los|todas las|dame los|muestr\w* los|exporta\w*)\s+"
        r"(de\s+)?(pedidos|clientes|emails|mails|ordenes|compradores|usuarios)\b")),
    ("customer_data", re.compile(
        r"\b(base de datos|dump|csv|tabla)\b.{0,30}\b(clientes|pedidos|usuarios)\b")),
)

# Frases que indican que una promesa de descuento se niega ("no ofrecemos descuentos").
NEGATION_RE = re.compile(r"\bno\s+(ofrecemos|aplicamos|tenemos|hay|manejamos|damos)\b")
DISCOUNT_RE = re.compile(r"(\bdescuento\w*|\bcupon\w*|\brebaja\w*|\bpromocion\w*)")
# Porcentaje ligado a una promesa ("20% de descuento", "descuento del 20%").
# Un porcentaje suelto (p. ej. "Teclado 75%") no es una promesa.
PERCENT_OFF_RE = re.compile(
    r"\d{1,3}\s?%\s*(de\s+)?(off|descuento|rebaja)|"
    r"(descuento|rebaja|off)\w*\s+(del\s+|de\s+)?\d{1,3}\s?%"
)
FREE_SHIPPING_RE = re.compile(r"\benvio\b.{0,15}\b(gratis|gratuito)\b")
FREE_SHIPPING_CONDITION_RE = re.compile(
    r"(a partir de|desde|superes|superen|superar|supera|mayor a|mayores a|minimo|>=)"
)
SKU_TOKEN_RE = re.compile(r"\b[A-Z]{3}-\d{3}\b")


@dataclass(frozen=True)
class InputVerdict:
    allowed: bool
    category: str | None = None


@dataclass
class OutputVerdict:
    violations: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return not self.violations


def check_input(message: str) -> InputVerdict:
    if len(message) > MAX_INPUT_CHARS:
        return InputVerdict(False, "input_too_long")
    normalized = normalize_text(message)
    for category, pattern in INPUT_RULES:
        if pattern.search(normalized):
            return InputVerdict(False, category)
    return InputVerdict(True)


def _is_negated(text: str) -> bool:
    return bool(NEGATION_RE.search(text))


def check_output(
    turn: AssistantTurn,
    catalog_skus: set[str],
    allowed_skus: set[str] | None = None,
) -> OutputVerdict:
    """Valida una respuesta candidata.

    - `invented_sku`: un SKU del texto o de recommended_skus no existe en el catálogo.
    - `sku_not_grounded`: se recomienda un SKU válido que no fue devuelto por herramientas
      en este turno (solo si se pasa `allowed_skus`).
    - `unauthorized_discount`: se promete descuento/cupón/porcentaje fuera de política.
    - `unconditional_free_shipping`: envío gratis sin condición de umbral.
    """
    verdict = OutputVerdict()
    text = normalize_text(turn.reply)

    mentioned = set(SKU_TOKEN_RE.findall(turn.reply))
    invented = (mentioned | set(turn.recommended_skus)) - catalog_skus
    if invented:
        verdict.violations.append("invented_sku")

    if allowed_skus is not None and set(turn.recommended_skus) - allowed_skus:
        verdict.violations.append("sku_not_grounded")

    if PERCENT_OFF_RE.search(text) or (DISCOUNT_RE.search(text) and not _is_negated(text)):
        verdict.violations.append("unauthorized_discount")

    if FREE_SHIPPING_RE.search(text) and not (
        FREE_SHIPPING_CONDITION_RE.search(text) or _is_negated(text)
    ):
        verdict.violations.append("unconditional_free_shipping")

    return verdict


def blocked_reply(category: str | None) -> str:
    if category == "input_too_long":
        return "El mensaje es demasiado largo. Escribilo en una consulta más corta."
    return (
        "No puedo ayudar con esa solicitud. Puedo buscar productos, consultar el estado "
        "de un pedido (con número y email) y explicar la política de envíos."
    )


SAFE_HANDOFF_REPLY = (
    "No puedo confirmar esa información con seguridad. Te derivo con un agente humano "
    "del equipo de atención."
)

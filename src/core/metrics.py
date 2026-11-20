"""Métricas por turno en JSONL append-only.

Regla de privacidad: el registro NUNCA incluye el texto del usuario ni la
respuesta, solo metadatos (intención, SKUs, tokens, costo, latencia, violaciones).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def estimate_cost_usd(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    pricing: dict[str, Any],
) -> float:
    """Costo estimado en USD. Precios por 1K tokens de config.yaml."""
    if not model or model not in pricing:
        return 0.0
    price = pricing[model]
    cost = (input_tokens / 1000) * float(price["input"]) + (output_tokens / 1000) * float(price["output"])
    return round(cost, 8)


def build_record(**fields: Any) -> dict[str, Any]:
    record = {"ts": datetime.now(timezone.utc).isoformat()}
    record.update(fields)
    return record


def append_metrics(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")

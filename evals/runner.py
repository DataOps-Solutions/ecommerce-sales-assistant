#!/usr/bin/env python3
"""Runner de evals: dataset de venta + adversariales, en modo offline determinista.

Uso:
  python evals/runner.py --offline              # genera data/evals_report.md
  python evals/runner.py --offline --compare    # además falla (exit 1) si no se cumplen umbrales

--offline es obligatorio: los evals nunca usan ni piden credenciales de proveedores.
Cada escenario corre con sesión y archivo de métricas temporales (no contamina data/).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.agent import SalesAssistant  # noqa: E402
from src.core.config import load_config, resolve_path  # noqa: E402
from src.core.schemas import AssistantTurn  # noqa: E402
from src.tools.store_tools import normalize_text  # noqa: E402

DATASET = ROOT / "evals" / "dataset.jsonl"
ADVERSARIAL = ROOT / "evals" / "adversarial.jsonl"


@dataclass
class ScenarioResult:
    id: str
    category: str
    input: str
    passed: bool
    turn: AssistantTurn | None
    failures: list[str] = field(default_factory=list)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path.name}:{lineno} JSON inválido") from exc
    return rows


def check_expectations(turn: AssistantTurn, expect: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    reply = normalize_text(turn.reply)
    if "intent" in expect and turn.intent != expect["intent"]:
        failures.append(f"intent={turn.intent} (esperado {expect['intent']})")
    if "blocked" in expect and (turn.intent == "blocked") != expect["blocked"]:
        failures.append(f"blocked={turn.intent == 'blocked'} (esperado {expect['blocked']})")
    if "requires_human" in expect and turn.requires_human != expect["requires_human"]:
        failures.append(f"requires_human={turn.requires_human}")
    for sku in expect.get("skus_include", []):
        if sku not in turn.recommended_skus:
            failures.append(f"falta SKU {sku}")
    for sku in expect.get("skus_exclude", []):
        if sku in turn.recommended_skus:
            failures.append(f"SKU no permitido {sku}")
    for text in expect.get("reply_contains", []):
        if normalize_text(text) not in reply:
            failures.append(f"respuesta sin '{text}'")
    for text in expect.get("reply_not_contains", []):
        if normalize_text(text) in reply:
            failures.append(f"respuesta contiene '{text}'")
    return failures


def run_scenarios(rows: list[dict[str, Any]], cfg: dict[str, Any], workdir: Path) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for row in rows:
        assistant = SalesAssistant(
            cfg,
            offline=True,
            metrics_file=workdir / "evals_metrics.jsonl",
            sleep=lambda _s: None,
        )
        turn = assistant.handle(row["input"]).turn
        failures = check_expectations(turn, row["expect"])
        results.append(ScenarioResult(
            id=row["id"], category=row["category"], input=row["input"],
            passed=not failures, turn=turn, failures=failures,
        ))
    return results


def rate(results: list[ScenarioResult]) -> float:
    return sum(r.passed for r in results) / len(results) if results else 0.0


def build_report(
    dataset: list[ScenarioResult],
    adversarial: list[ScenarioResult],
    thresholds: dict[str, float],
) -> str:
    ds_rate = rate(dataset)
    adv_rate = rate(adversarial)
    ds_ok = ds_rate >= thresholds["dataset_accuracy"]
    adv_ok = adv_rate >= thresholds["adversarial_block_rate"]

    lines = [
        "# Evals: ecommerce-sales-assistant",
        "",
        "Modo: **offline determinista** (router + herramientas + guardrails, sin LLM). "
        "Mide la lógica del motor, no la calidad de ningún modelo de lenguaje.",
        "",
        "## Resultado",
        "",
        "| Suite | Escenarios | Aciertos | Tasa | Umbral | Estado |",
        "|---|---:|---:|---:|---:|---|",
        f"| dataset (venta, stock, envío, tracking) | {len(dataset)} | "
        f"{sum(r.passed for r in dataset)} | {ds_rate:.2%} | {thresholds['dataset_accuracy']:.0%} | "
        f"{'OK' if ds_ok else 'FALLA'} |",
        f"| adversarial (precio, injection, datos ajenos) | {len(adversarial)} | "
        f"{sum(r.passed for r in adversarial)} | {adv_rate:.2%} | {thresholds['adversarial_block_rate']:.0%} | "
        f"{'OK' if adv_ok else 'FALLA'} |",
        "",
        "## Dataset por categoría",
        "",
        "| Categoría | Escenarios | Tasa |",
        "|---|---:|---:|",
    ]
    for cat in sorted({r.category for r in dataset}):
        subset = [r for r in dataset if r.category == cat]
        lines.append(f"| {cat} | {len(subset)} | {rate(subset):.2%} |")

    lines += ["", "## Detalle", "", "| ID | Suite | Resultado | Intención | SKUs | Bloqueado |", "|---|---|---|---|---|---|"]
    for suite, results in (("dataset", dataset), ("adversarial", adversarial)):
        for r in results:
            t = r.turn
            skus = ", ".join(t.recommended_skus) if t and t.recommended_skus else "-"
            intent = t.intent if t else "-"
            blocked = "sí" if t and t.intent == "blocked" else "no"
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"| {r.id} | {suite} | {status} | {intent} | {skus} | {blocked} |")

    failed = [r for r in dataset + adversarial if not r.passed]
    lines += ["", "## Fallos", ""]
    if failed:
        for r in failed:
            lines.append(f"- **{r.id}** ({r.category}): {'; '.join(r.failures)}")
    else:
        lines.append("Sin fallos.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="obligatorio: modo determinista sin LLM")
    parser.add_argument("--compare", action="store_true", help="falla si no se cumplen los umbrales")
    args = parser.parse_args(argv)
    if not args.offline:
        print("error: los evals solo corren con --offline (sin credenciales)", file=sys.stderr)
        return 2

    cfg = load_config()
    thresholds = cfg["evals"]["thresholds"]
    with tempfile.TemporaryDirectory() as tmp:
        dataset = run_scenarios(load_jsonl(DATASET), cfg, Path(tmp))
        adversarial = run_scenarios(load_jsonl(ADVERSARIAL), cfg, Path(tmp))

    report = build_report(dataset, adversarial, thresholds)
    report_path = resolve_path(cfg["evals"]["report_path"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    ds_rate = rate(dataset)
    adv_rate = rate(adversarial)
    print(f"dataset:     {sum(r.passed for r in dataset)}/{len(dataset)} ({ds_rate:.2%})")
    print(f"adversarial: {sum(r.passed for r in adversarial)}/{len(adversarial)} ({adv_rate:.2%})")
    print(f"reporte: {report_path.relative_to(ROOT)}")

    if args.compare:
        ok = ds_rate >= thresholds["dataset_accuracy"] and adv_rate >= thresholds["adversarial_block_rate"]
        if not ok:
            print("FAIL: umbrales de evals no cumplidos", file=sys.stderr)
            return 1
        print("OK: umbrales cumplidos")
    return 0


if __name__ == "__main__":
    sys.exit(main())

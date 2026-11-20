#!/usr/bin/env python3
"""CLI de ecommerce-sales-assistant.

Modos:
  --chat               loop interactivo (comandos: /reset, /exit)
  --message "..."      turno único
  --offline            motor determinista, sin llamadas a LLM
  --full               imprime JSON con respuesta, SKUs y métricas
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.agent import SalesAssistant, TurnResult  # noqa: E402


def render(result: TurnResult, full: bool) -> str:
    turn = result.turn
    if full:
        payload = {
            "reply": turn.reply,
            "intent": turn.intent,
            "recommended_skus": turn.recommended_skus,
            "confidence": turn.confidence,
            "requires_human": turn.requires_human,
            "metrics": result.metrics,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    suffix = "\n(Derivado a un agente humano)" if turn.requires_human else ""
    return turn.reply + suffix


def run_chat(
    assistant: SalesAssistant,
    *,
    full: bool,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> int:
    write("Asistente de ventas. Comandos: /reset (borra la memoria), /exit (salir).")
    while True:
        try:
            line = read("tú> ")
        except (EOFError, KeyboardInterrupt):
            write("")
            return 0
        text = line.strip()
        if not text:
            continue
        if text == "/exit":
            return 0
        if text == "/reset":
            assistant.reset()
            write("Memoria reiniciada.")
            continue
        write(f"asistente> {render(assistant.handle(text), full)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Asistente conversacional de ventas e-commerce")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--chat", action="store_true", help="loop interactivo en consola")
    mode.add_argument("--message", metavar="TEXTO", help="turno único")
    parser.add_argument("--offline", action="store_true", help="sin LLM: motor determinista")
    parser.add_argument("--full", action="store_true", help="salida JSON con métricas y SKUs")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.chat and args.message is None:
        parser.print_help()
        return 2

    assistant = SalesAssistant(offline=args.offline)
    if args.chat:
        return run_chat(assistant, full=args.full)

    result = assistant.handle(args.message)
    print(render(result, args.full))
    return 0


if __name__ == "__main__":
    sys.exit(main())

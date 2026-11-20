"""Derivación a humano: solicitud explícita vs. fallback de guardrail de salida."""

from __future__ import annotations

from src.core.agent import SalesAssistant
from src.core.guardrails import SAFE_HANDOFF_REPLY
from src.core.responder import HANDOFF_REPLY


def test_explicit_human_request_gets_handoff_message(cfg, metrics_file, no_sleep):
    bot = SalesAssistant(cfg, offline=True, metrics_file=metrics_file, sleep=no_sleep)
    result = bot.handle("Quiero hablar con una persona")
    assert result.turn.intent == "human_handoff"
    assert result.turn.reply == HANDOFF_REPLY
    assert "no puedo confirmar" not in result.turn.reply.lower()


def test_guardrail_fallback_uses_safe_message(cfg, metrics_file, no_sleep):
    bot = SalesAssistant(cfg, offline=True, metrics_file=metrics_file, sleep=no_sleep)
    # Fuerza el camino de fallback: ninguna candidata pasa el guardrail de salida.
    bot._skus = frozenset()  # catálogo vacío => cualquier SKU recomendado es inventado
    result = bot.handle("Quiero un cargador USB-C de 65W")
    assert result.turn.intent == "human_handoff"
    assert result.turn.reply == SAFE_HANDOFF_REPLY
    assert result.turn.requires_human is True

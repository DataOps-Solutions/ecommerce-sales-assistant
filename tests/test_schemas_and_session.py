"""Contrato AssistantTurn y ventana deslizante de la sesión."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.schemas import AssistantTurn
from src.core.session import ChatSession


def _base(**overrides):
    data = {
        "reply": "Hola",
        "intent": "product_discovery",
        "recommended_skus": [],
        "confidence": 0.5,
        "requires_human": False,
    }
    data.update(overrides)
    return data


def test_valid_turn_is_accepted():
    turn = AssistantTurn(**_base(recommended_skus=["AUD-001"], confidence=1.0))
    assert turn.recommended_skus == ["AUD-001"]


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_bounds(confidence):
    with pytest.raises(ValidationError):
        AssistantTurn(**_base(confidence=confidence))


def test_invalid_intent_rejected():
    with pytest.raises(ValidationError):
        AssistantTurn(**_base(intent="ventas"))


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        AssistantTurn(**_base(descuento=50))


@pytest.mark.parametrize("sku", ["aud-001", "AUD001", "AUDIO-1", "AUD-01"])
def test_malformed_sku_rejected(sku):
    with pytest.raises(ValidationError):
        AssistantTurn(**_base(recommended_skus=[sku]))


def test_duplicate_skus_rejected():
    with pytest.raises(ValidationError):
        AssistantTurn(**_base(recommended_skus=["AUD-001", "AUD-001"]))


def test_blocked_turn_cannot_recommend_skus():
    with pytest.raises(ValidationError):
        AssistantTurn(**_base(intent="blocked", recommended_skus=["AUD-001"]))


def test_session_keeps_only_last_max_turns_exchanges():
    session = ChatSession(max_turns=6)
    for i in range(10):
        session.add_exchange(f"u{i}", f"a{i}")
    assert len(session) == 6
    messages = session.messages()
    assert len(messages) == 12
    assert messages[0] == {"role": "user", "content": "u4"}
    assert messages[-1] == {"role": "assistant", "content": "a9"}


def test_session_window_is_bounded_regardless_of_length():
    session = ChatSession(max_turns=3)
    for i in range(500):
        session.add_exchange("x" * 50, "y" * 50)
    assert len(session.messages()) == 6


def test_session_reset_clears_history_and_context():
    session = ChatSession()
    session.add_exchange("hola", "hola!")
    session.remember(order_id="ORD-1001", email=None)
    session.reset()
    assert len(session) == 0
    assert session.context == {}


def test_session_remember_skips_empty_values():
    session = ChatSession()
    session.remember(email=None, order_id="")
    assert session.context == {}


def test_session_rejects_invalid_window():
    with pytest.raises(ValueError):
        ChatSession(max_turns=0)

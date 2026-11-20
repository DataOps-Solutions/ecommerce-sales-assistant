"""Orquestador de un turno.

Flujo: guardrail de entrada -> router + herramientas -> LLM (opcional, solo redacta)
-> guardrail de salida (con fallback determinista) -> escalamiento -> métricas.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.core.config import forced_provider, load_config, metrics_path
from src.core.guardrails import SAFE_HANDOFF_REPLY, check_input, check_output
from src.core.llm import Provider, build_chain, generate_turn
from src.core.metrics import append_metrics, build_record, estimate_cost_usd
from src.core.responder import blocked_turn, compose_offline, execute_plan, handoff_turn
from src.core.router import route
from src.core.schemas import AssistantTurn
from src.core.session import ChatSession
from src.tools.store_tools import catalog_skus, normalize_text


@dataclass
class TurnResult:
    turn: AssistantTurn
    metrics: dict[str, Any] = field(default_factory=dict)


class SalesAssistant:
    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        *,
        offline: bool = False,
        chain: list[Provider] | None = None,
        metrics_file: Path | None = None,
        session: ChatSession | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg = cfg if cfg is not None else load_config()
        self.offline = offline
        if chain is not None:
            self._chain = chain
        elif offline:
            self._chain = []
        else:
            self._chain = build_chain(self.cfg, forced_provider())
        self.session = session or ChatSession(max_turns=int(self.cfg["conversation"]["max_turns"]))
        self.metrics_file = metrics_file or metrics_path(self.cfg)
        self.session_id = uuid.uuid4().hex[:12]
        self._sleep = sleep
        self._turn_index = 0
        self._skus = catalog_skus()

    # --- API pública -----------------------------------------------------

    def handle(self, message: str) -> TurnResult:
        self._turn_index += 1
        started = time.perf_counter()
        history_len = len(self.session)

        verdict = check_input(message)
        if not verdict.allowed:
            turn = blocked_turn(verdict.category)
            return self._finish(
                turn, started, history_len, mode="guardrail", guardrail=verdict.category,
            )

        plan = route(message, self.session.context)
        results = execute_plan(plan)
        threshold = float(self.cfg["shipping_policy"]["free_shipping_threshold_ars"])
        deterministic = compose_offline(plan, results, threshold)

        candidates: list[tuple[str, AssistantTurn, Any]] = []
        llm_meta: dict[str, Any] = {"provider": None, "model": None, "in": 0, "out": 0,
                                    "attempts": 0, "errors": []}
        fallback_reason = None
        if self._chain:
            payload = json.dumps({
                "message": message,
                "history": self.session.messages(),
                "route": plan.as_dict(),
                "tool_results": {
                    "products": results.products,
                    "product": results.product,
                    "order": results.order,
                    "order_reason": results.order_reason,
                    "policy": {"free_shipping_threshold_ars": threshold, "discounts_allowed": False},
                },
            }, ensure_ascii=False)
            pcfg = self.cfg["providers"]
            outcome = generate_turn(
                self._chain, payload,
                max_retries=int(pcfg["max_retries"]),
                backoff_base_s=float(pcfg["backoff_base_s"]),
                sleep=self._sleep,
            )
            llm_meta = {
                "provider": outcome.provider, "model": outcome.model,
                "in": outcome.input_tokens, "out": outcome.output_tokens,
                "attempts": outcome.attempts, "errors": outcome.errors,
            }
            if outcome.turn is not None:
                candidates.append(("llm", outcome.turn, results.grounded_skus))
            else:
                fallback_reason = "llm_unavailable"
        elif not self.offline:
            fallback_reason = "no_provider_configured"
        candidates.append(("offline", deterministic, None))

        mode, chosen, violations = "offline", None, []
        for name, turn, allowed in candidates:
            verdict_out = check_output(turn, self._skus, allowed)
            if verdict_out.allowed:
                mode, chosen = name, turn
                break
            violations.extend(verdict_out.violations)
        if chosen is None:
            # Ninguna respuesta pasó el guardrail de salida: derivación segura.
            mode, chosen = "offline", handoff_turn(SAFE_HANDOFF_REPLY, confidence=0.5)

        final = self._escalate(chosen, message, results)
        self.session.add_exchange(message, final.reply)
        self.session.remember(email=plan.email, order_id=plan.order_id)

        return self._finish(
            final, started, history_len,
            mode=mode,
            guardrail=None,
            violations=violations,
            plan_intent=plan.intent,
            tool_calls=results.tool_calls,
            llm=llm_meta,
            fallback_reason=fallback_reason,
        )

    def reset(self) -> None:
        self.session.reset()

    # --- internos --------------------------------------------------------

    def _escalate(self, turn: AssistantTurn, message: str, results: Any) -> AssistantTurn:
        esc = self.cfg["escalation"]
        reasons = []
        if turn.intent == "human_handoff":
            reasons.append("intent")
        if turn.confidence < float(esc["min_confidence"]):
            reasons.append("low_confidence")
        normalized = normalize_text(message)
        if any(normalize_text(k) in normalized for k in esc["keywords"]):
            reasons.append("keyword")
        if results.order and results.order["status"] in esc["escalate_order_statuses"]:
            reasons.append("order_status")
        requires = turn.requires_human or bool(reasons)
        return turn.model_copy(update={"requires_human": requires})

    def _finish(
        self,
        turn: AssistantTurn,
        started: float,
        history_len: int,
        *,
        mode: str,
        guardrail: str | None,
        violations: list[str] | None = None,
        plan_intent: str | None = None,
        tool_calls: list[str] | None = None,
        llm: dict[str, Any] | None = None,
        fallback_reason: str | None = None,
    ) -> TurnResult:
        # Los turnos bloqueados por guardrail no se guardan en el historial (ver handle).
        llm = llm or {"provider": None, "model": None, "in": 0, "out": 0, "attempts": 0, "errors": []}
        pricing = self.cfg.get("pricing_usd_per_1k_tokens", {})
        cost = estimate_cost_usd(llm["model"], llm["in"], llm["out"], pricing)
        record = build_record(
            session_id=self.session_id,
            turn=self._turn_index,
            history_exchanges=history_len,
            mode=mode,
            guardrail_input=guardrail,
            intent=turn.intent,
            plan_intent=plan_intent,
            confidence=turn.confidence,
            requires_human=turn.requires_human,
            recommended_skus=list(turn.recommended_skus),
            tool_calls=list(tool_calls or []),
            output_violations=list(violations or []),
            provider=llm["provider"],
            model=llm["model"],
            llm_attempts=llm["attempts"],
            llm_errors=list(llm["errors"]),
            fallback_reason=fallback_reason,
            input_tokens=llm["in"],
            output_tokens=llm["out"],
            cost_usd=cost,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        append_metrics(record, self.metrics_file)
        return TurnResult(turn=turn, metrics=record)

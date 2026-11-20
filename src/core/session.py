"""Memoria multi-turno en RAM con ventana deslizante.

Se guardan solo los últimos `max_turns` intercambios (usuario + asistente), así el
prompt del LLM tiene tamaño acotado. Los turnos bloqueados por guardrails no se
guardan en el historial para que un ataque no contamine turnos posteriores.

El contexto (último email y último número de pedido) permite preguntas como
"¿y el pedido?" sin repetir datos. No se persiste en disco.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Exchange:
    user: str
    assistant: str


@dataclass
class ChatSession:
    max_turns: int = 6
    exchanges: deque[Exchange] = field(init=False)
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_turns < 1:
            raise ValueError("max_turns debe ser >= 1")
        self.exchanges = deque(maxlen=self.max_turns)

    def add_exchange(self, user: str, assistant: str) -> None:
        self.exchanges.append(Exchange(user=user, assistant=assistant))

    def messages(self) -> list[dict[str, str]]:
        """Historial en formato chat (role/content) dentro de la ventana."""
        out: list[dict[str, str]] = []
        for ex in self.exchanges:
            out.append({"role": "user", "content": ex.user})
            out.append({"role": "assistant", "content": ex.assistant})
        return out

    def remember(self, **values: Any) -> None:
        """Guarda valores de contexto no nulos (p. ej. email, order_id)."""
        for key, value in values.items():
            if value:
                self.context[key] = value

    def reset(self) -> None:
        self.exchanges.clear()
        self.context.clear()

    def __len__(self) -> int:
        return len(self.exchanges)

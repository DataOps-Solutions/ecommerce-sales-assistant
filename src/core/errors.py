"""Jerarquía de errores del asistente.

- RetryableProviderError: 408/409/429/5xx y timeouts. Se reintenta con backoff.
- NonRetryableProviderError: 400/401/403/404 y errores de configuración. No se reintenta;
  se pasa al siguiente proveedor de la cadena.
- ContractError: la salida del LLM no cumple AssistantTurn. Se descarta el candidato.
"""


class AssistantError(Exception):
    """Base de todos los errores del asistente."""


class RetryableProviderError(AssistantError):
    """Error transitorio de proveedor: reintentable."""


class NonRetryableProviderError(AssistantError):
    """Error permanente de proveedor (auth, configuración, request inválido)."""


class ContractError(AssistantError):
    """La respuesta del proveedor no cumple el contrato AssistantTurn."""

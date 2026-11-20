"""Construcción de la cadena de proveedores a partir de config y variables de entorno."""

from __future__ import annotations

import pytest

import src.core.llm as llm
from src.core.errors import NonRetryableProviderError


class _Stub:
    def __init__(self, name: str, model: str, *args, **kwargs):
        self.name = name
        self.model = model


class _StubOpenAI(_Stub):
    def __init__(self, model, api_key, timeout_s, max_tokens, temperature, base_url=None):
        super().__init__("openai", model)


class _StubAnthropic(_Stub):
    def __init__(self, model, api_key, timeout_s, max_tokens, temperature):
        super().__init__("anthropic", model)


class _StubOpenCode(_Stub):
    def __init__(self, model, api_key, timeout_s, max_tokens, temperature, base_url=None):
        super().__init__("opencode", model)


@pytest.fixture
def stub_providers(monkeypatch):
    monkeypatch.setattr(llm, "OpenAIProvider", _StubOpenAI)
    monkeypatch.setattr(llm, "AnthropicProvider", _StubAnthropic)
    monkeypatch.setattr(llm, "OpenCodeProvider", _StubOpenCode)


@pytest.fixture
def clean_env(monkeypatch):
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENCODE_API_KEY",
                "OPENCODE_BASE_URL", "ASSISTANT_PROVIDER"):
        monkeypatch.delenv(key, raising=False)


def test_no_keys_means_empty_chain(cfg, clean_env, stub_providers):
    assert llm.build_chain(cfg) == []


def test_default_provider_is_openai_then_fallbacks(cfg, clean_env, stub_providers, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-value-not-real")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-value-not-real")
    monkeypatch.setenv("OPENCODE_API_KEY", "test-value-not-real")
    monkeypatch.setenv("OPENCODE_BASE_URL", "https://example.invalid/v1")
    names = [p.name for p in llm.build_chain(cfg)]
    assert names == ["openai", "anthropic", "opencode"]


def test_assistant_provider_env_overrides_default(cfg, clean_env, stub_providers, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-value-not-real")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-value-not-real")
    chain = llm.build_chain(cfg, forced="anthropic")
    assert [p.name for p in chain] == ["anthropic", "openai"]


def test_opencode_requires_base_url(cfg, clean_env, stub_providers, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "test-value-not-real")
    assert llm.build_chain(cfg, forced="opencode") == []


def test_missing_sdk_skips_provider_instead_of_crashing(cfg, clean_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-value-not-real")

    def _missing_sdk(*args, **kwargs):
        raise NonRetryableProviderError("openai SDK no instalado")

    monkeypatch.setattr(llm, "OpenAIProvider", _missing_sdk)
    assert llm.build_chain(cfg) == []

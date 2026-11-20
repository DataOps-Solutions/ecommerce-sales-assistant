"""Configuración común: rutas y métricas aisladas por test."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import load_config  # noqa: E402


@pytest.fixture
def cfg() -> dict:
    return load_config()


@pytest.fixture
def metrics_file(tmp_path: Path) -> Path:
    return tmp_path / "metrics.jsonl"


@pytest.fixture
def no_sleep():
    return lambda _seconds: None

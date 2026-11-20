"""Carga de configuración: config.yaml (no secreta) + variables de entorno (.env)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.yaml"

load_dotenv(ROOT / ".env", override=False)


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("config.yaml debe ser un mapping")
    return data


def resolve_path(relative: str) -> Path:
    """Convierte una ruta relativa de config.yaml a absoluta bajo ROOT."""
    path = Path(relative)
    return path if path.is_absolute() else ROOT / path


def metrics_path(cfg: dict[str, Any]) -> Path:
    override = os.environ.get("CHAT_METRICS_PATH", "").strip()
    if override:
        return Path(override)
    return resolve_path(cfg["metrics"]["path"])


def forced_provider() -> str | None:
    value = os.environ.get("ASSISTANT_PROVIDER", "").strip().lower()
    return value or None


def env_value(name: str) -> str:
    return os.environ.get(name, "").strip()

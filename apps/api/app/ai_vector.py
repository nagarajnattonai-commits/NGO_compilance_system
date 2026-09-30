"""Portable deterministic vector storage used when native pgvector is not configured."""
from __future__ import annotations

import json
import math
import os

from .ai_provider import AiProviderError


def vector_backend() -> str:
    configured = os.getenv("AI_VECTOR_BACKEND")
    if os.getenv("APP_ENV") == "production" and not configured:
        raise AiProviderError("VECTOR_BACKEND_UNAVAILABLE")
    backend = (configured or "portable_exact").strip().lower()
    if backend != "portable_exact":
        raise AiProviderError("VECTOR_BACKEND_UNAVAILABLE")
    return backend


def encode_vector(values: list[float]) -> str:
    if not values or len(values) > 4096 or any(not math.isfinite(float(value)) for value in values):
        raise AiProviderError("PROVIDER_UNAVAILABLE")
    return json.dumps([round(float(value), 10) for value in values], separators=(",", ":"))


def decode_vector(value: str) -> list[float]:
    try:
        result = [float(item) for item in json.loads(value)]
        if not result or any(not math.isfinite(item) for item in result):
            raise ValueError()
        return result
    except Exception:
        return []


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else -1.0

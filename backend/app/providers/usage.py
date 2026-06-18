"""Token-usage normalization across providers -> canonical fields.

Providers report usage under many different keys (OpenAI ``prompt_tokens`` /
``completion_tokens``; Gemini ``prompt_token_count`` / ``candidates_token_count``;
LiteLLM ``Usage`` objects; nested ``*_token_details`` for cached / reasoning tokens).
This module collapses any of those into a single canonical ``NormalizedUsage`` so the
rest of Colosseum (cost, persistence, scoring) never special-cases a provider.

Borrows the field-aliasing approach from superclaims-ai
``pricing/estimated_vertex_cost.extract_token_fields_for_cost`` and extends it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class NormalizedUsage:
    input_tokens: int = 0
    output_tokens: int = 0  # excludes thinking tokens (broken out below)
    thinking_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return None


def to_jsonable(raw: Any) -> dict[str, Any]:
    """Best-effort JSON-able view of a raw usage object (LiteLLM Usage, dict, etc.)."""
    if raw is None:
        return {}
    if hasattr(raw, "model_dump"):
        try:
            return raw.model_dump()  # pydantic
        except Exception:
            pass
    if hasattr(raw, "dict"):
        try:
            return raw.dict()
        except Exception:
            pass
    try:
        return json.loads(json.dumps(raw, default=lambda o: getattr(o, "__dict__", str(o))))
    except (TypeError, ValueError):
        return {"_unparsed": str(raw)}


def normalize_usage(raw: Any) -> NormalizedUsage:
    """Collapse any provider usage payload into canonical token classes.

    ``output_tokens`` is returned *net of* thinking/reasoning tokens so cost can price them
    separately; ``total_tokens`` is preserved from the provider when present, else derived.
    """
    u = to_jsonable(raw)

    inp = _to_int(
        _first(u, "input_tokens", "prompt_tokens", "prompt_token_count", "input_token_count")
    )
    out = _to_int(
        _first(
            u,
            "output_tokens",
            "completion_tokens",
            "candidates_token_count",
            "output_token_count",
        )
    )
    total = _to_int(_first(u, "total_tokens", "total_token_count"))

    # --- cached input tokens (nested details first, then flat aliases) ---
    cached = 0
    details = u.get("prompt_tokens_details") or u.get("input_token_details")
    if isinstance(details, dict):
        cached = _to_int(
            _first(details, "cached_tokens", "cache_read", "cached_content_token_count")
        )
    if cached == 0:
        cached = _to_int(_first(u, "cached_content_token_count", "cached_tokens", "cache_read_input_tokens"))

    # --- reasoning / thinking tokens ---
    thinking = 0
    out_details = u.get("completion_tokens_details") or u.get("output_token_details")
    if isinstance(out_details, dict):
        thinking = _to_int(
            _first(out_details, "reasoning_tokens", "reasoning", "thoughts_token_count")
        )
    if thinking == 0:
        thinking = _to_int(_first(u, "thoughts_token_count", "reasoning_tokens"))

    # Provider ``output``/``completion`` counts sometimes already include reasoning tokens.
    # Keep ``output_tokens`` net of thinking so pricing doesn't double-count.
    if thinking and out >= thinking:
        out = out - thinking

    if total == 0 and (inp or out or thinking):
        total = inp + out + thinking

    return NormalizedUsage(
        input_tokens=inp,
        output_tokens=out,
        thinking_tokens=thinking,
        cached_tokens=cached,
        total_tokens=total,
    )

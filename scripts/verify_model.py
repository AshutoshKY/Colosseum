"""Cheap live structured-output check for one catalog model.

Usage: uv run python scripts/verify_model.py --model gemini-3.1-pro
"""

from __future__ import annotations

import argparse
import asyncio

from app.providers.gateway import ModelGateway
from pydantic import BaseModel


class _Ok(BaseModel):
    ok: bool


async def verify(model_id: str, thinking_level: str | None = None) -> bool:
    from app.providers.registry import get_capability
    cap = get_capability(model_id)
    max_tokens = 2048 if cap.thinking else 512
    result = await ModelGateway(trace=False).structured(
        model_id=model_id,
        system="Return the requested JSON only.",
        instruction='Return {"ok": true}.',
        schema=_Ok,
        config={
            "max_output_tokens": max_tokens,
            **({"thinking_level": thinking_level} if thinking_level else {}),
        },
    )
    if result.valid and result.parsed and result.parsed.ok:
        print(f"{model_id}: ok")
        return True
    error_msg = result.error or result.skip_reason or "invalid response"
    print(f"{model_id}: failed: {error_msg}")
    raise RuntimeError(error_msg)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Colosseum catalog id")
    parser.add_argument(
        "--thinking-level", choices=("minimal", "low", "medium", "high"), default=None
    )
    args = parser.parse_args()
    return 0 if asyncio.run(verify(args.model, args.thinking_level)) else 1


if __name__ == "__main__":
    raise SystemExit(main())

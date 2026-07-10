"""List and cheaply smoke-test Bedrock models with the configured bearer token.

The token is never printed. It typically expires after about 12 hours.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml
from app.core.config import get_settings
from app.providers.capabilities import Provider
from app.providers.registry import get_capability, list_models

_EXPIRED = "AWS_BEARER_TOKEN_BEDROCK expired — refresh it in .env"


def _is_expired(exc: Exception) -> bool:
    message = str(exc).lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return "expiredtoken" in message or (
        code in {401, 403} and "expired" in message and "token" in message
    )


def _list_direct(token: str, region: str) -> list[str]:
    request = Request(
        f"https://bedrock.{region}.amazonaws.com/foundation-models",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed AWS hostname
            payload = json.load(response)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if _is_expired(RuntimeError(f"{exc.code}: {body}")):
            raise RuntimeError(_EXPIRED) from exc
        raise
    return [item["modelId"] for item in payload.get("modelSummaries", [])]


def list_foundation_models(token: str, region: str) -> list[str]:
    """Use boto3 when possible, then fall back to the bearer-token HTTPS endpoint."""
    try:
        import boto3

        response = boto3.client("bedrock", region_name=region).list_foundation_models()
        return [item["modelId"] for item in response.get("modelSummaries", [])]
    except Exception as exc:  # boto3 may not understand Bedrock bearer auth in older botocore
        if _is_expired(exc):
            raise RuntimeError(_EXPIRED) from exc
        return _list_direct(token, region)


def _candidate_ids(requested: list[str] | None) -> list[str]:
    if requested:
        return requested
    return [cap.model_id for cap in list_models(provider=Provider.bedrock)]


async def _smoke(catalog_id: str, token: str, region: str) -> tuple[bool, str | None]:
    import litellm

    try:
        cap = get_capability(catalog_id)
        await litellm.acompletion(
            model=cap.transport_model,
            api_key=token,
            aws_region_name=region,
            messages=[{"role": "user", "content": "Reply OK"}],
            max_tokens=1,
        )
        return True, None
    except Exception as exc:
        if _is_expired(exc):
            raise RuntimeError(_EXPIRED) from exc
        return False, f"{exc.__class__.__name__}: {exc}"


async def run(requested: list[str] | None) -> int:
    settings = get_settings()
    token = settings.aws_bearer_token_bedrock or os.environ.get(
        "AWS_BEARER_TOKEN_BEDROCK"
    )
    if not token:
        print("AWS_BEARER_TOKEN_BEDROCK is not set")
        return 2

    region = settings.aws_region_name
    available = list_foundation_models(token, region)
    print(f"Bedrock {region}: {len(available)} foundation models listed")

    verified = []
    for catalog_id in _candidate_ids(requested):
        ok, error = await _smoke(catalog_id, token, region)
        print(f"{catalog_id}: {'ok' if ok else f'fail: {error}'}")
        if ok:
            verified.append(get_capability(catalog_id))

    if verified:
        print("\nVerified YAML snippet:")
        print(
            yaml.safe_dump(
                [
                    {
                        "model_id": cap.model_id,
                        "litellm_model": cap.transport_model,
                        "enabled": True,
                        "verified": True,
                    }
                    for cap in verified
                ],
                sort_keys=False,
            ).rstrip()
        )
    return 0 if verified else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", help="catalog id; may be repeated")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.model))
    except RuntimeError as exc:
        print(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

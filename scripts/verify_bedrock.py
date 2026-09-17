"""List and cheaply smoke-test Bedrock models with configured IAM access or bearer token.

When AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are set, requests are signed with
AWS SigV4 on the fly (continuous auto-renewal, no 12-hour expiration).
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

_EXPIRED = "AWS Bedrock credentials/token expired — update AWS_ACCESS_KEY_ID & AWS_SECRET_ACCESS_KEY in .env"


def _is_expired(exc: Exception) -> bool:
    message = str(exc).lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return (
        "expiredtoken" in message
        or ("expired" in message and "token" in message)
        or (code in {401, 403} and "expired" in message)
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
        if _is_expired(exc) or _is_expired(RuntimeError(f"{exc.code}: {body}")):
            raise RuntimeError(_EXPIRED) from exc
        raise
    return [item["modelId"] for item in payload.get("modelSummaries", [])]


def list_foundation_models(
    region: str,
    *,
    access_key: str | None = None,
    secret_key: str | None = None,
    token: str | None = None,
) -> list[str]:
    """Use boto3 when possible, then fall back to the bearer-token HTTPS endpoint."""
    try:
        import boto3

        client_kwargs = {"region_name": region}
        if access_key and secret_key:
            client_kwargs["aws_access_key_id"] = access_key
            client_kwargs["aws_secret_access_key"] = secret_key
        response = boto3.client("bedrock", **client_kwargs).list_foundation_models()
        return [item["modelId"] for item in response.get("modelSummaries", [])]
    except Exception as exc:
        if _is_expired(exc):
            raise RuntimeError(_EXPIRED) from exc
        if token:
            return _list_direct(token, region)
        raise


def _candidate_ids(requested: list[str] | None) -> list[str]:
    if requested:
        return requested
    return [cap.model_id for cap in list_models(provider=Provider.bedrock)]


async def _smoke(
    catalog_id: str,
    region: str,
    *,
    access_key: str | None = None,
    secret_key: str | None = None,
    token: str | None = None,
) -> tuple[bool, str | None]:
    import litellm

    try:
        cap = get_capability(catalog_id)
        kwargs: dict = {
            "model": cap.transport_model,
            "aws_region_name": region,
            "messages": [{"role": "user", "content": "Reply OK"}],
            "max_tokens": 1,
        }
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key
            os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
        elif token:
            kwargs["api_key"] = token

        await litellm.acompletion(**kwargs)
        return True, None
    except Exception as exc:
        if _is_expired(exc):
            raise RuntimeError(_EXPIRED) from exc
        return False, f"{exc.__class__.__name__}: {exc}"


async def run(requested: list[str] | None, region_override: str | None = None) -> int:
    settings = get_settings()
    access_key = settings.aws_access_key_id or os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = settings.aws_secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY")
    token = settings.aws_bearer_token_bedrock or os.environ.get(
        "AWS_BEARER_TOKEN_BEDROCK"
    )
    if not (access_key and secret_key) and not token:
        print("Neither AWS IAM keys (AWS_ACCESS_KEY_ID & AWS_SECRET_ACCESS_KEY) nor AWS_BEARER_TOKEN_BEDROCK are set in .env")
        return 2

    region = region_override or settings.aws_region_name or "us-east-1"
    auth_mode = "IAM SigV4 (auto-renewing)" if (access_key and secret_key) else "Bearer token"
    print(f"Bedrock region: {region} | Auth mode: {auth_mode}")

    available = list_foundation_models(
        region, access_key=access_key, secret_key=secret_key, token=token
    )
    print(f"Bedrock {region}: {len(available)} foundation models listed")

    verified = []
    for catalog_id in _candidate_ids(requested):
        ok, error = await _smoke(
            catalog_id,
            region,
            access_key=access_key,
            secret_key=secret_key,
            token=token,
        )
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
    parser.add_argument("--region", default=None, help="AWS region (e.g. us-east-1, us-west-2, ap-south-1, eu-west-1)")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.model, region_override=args.region))
    except RuntimeError as exc:
        print(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

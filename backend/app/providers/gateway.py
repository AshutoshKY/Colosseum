"""``ModelGateway`` — the model-agnostic structured-output entrypoint.

``ModelGateway.structured(...)`` mirrors superclaims-ai's ``ainvoke_structured`` contract but
provider-agnostically:

1. Look up the model's ``ModelCapability``.
2. Run the provider adapter to normalize document/text input (PDF native vs rasterized).
3. Call **Instructor over LiteLLM** with the Pydantic ``response_model`` and the structured
   method chosen by capability (json_schema | json_mode | tools).
4. If structured output fails / validates poorly on a weak model, run the **free-text ->
   JSON-repair fallback ladder** (the idea borrowed from superclaims-ai ``agents/audit.py``).
5. Normalize usage, estimate cost, and return a ``GatewayResult`` with everything needed to
   persist a ``run_result`` row (tokens, cost, latency, parsed output, raw, retries, errors).

Credentials: LiteLLM's ``vertex_ai`` route reads ``vertex_credentials`` (inline service-account
JSON, as stored in superclaims-ai/.env ``GOOGLE_CLOUD_CREDENTIALS_JSON``) + ``vertex_project`` +
``vertex_location``. No secrets are committed.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, TypeVar
import instructor
import litellm
from pydantic import BaseModel, ValidationError

litellm.drop_params = True

from app.core.config import get_settings
from app.core.logging import get_logger
from app.providers.adapters import CapabilityGateError, DocumentInput, get_adapter
from app.providers.capabilities import ModelCapability, StructuredMethod
from app.providers.pricing import EstimatedCost, estimate_cost
from app.providers.registry import get_capability
from app.providers.usage import NormalizedUsage, normalize_usage, to_jsonable

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# instructor.Mode chosen per capability.
_MODE_BY_METHOD = {
    StructuredMethod.json_schema: "JSON_SCHEMA",
    StructuredMethod.json_mode: "JSON",
    StructuredMethod.tools: "TOOLS",
}


class ProviderAuthError(RuntimeError):
    """A provider credential is missing or needs refreshing."""


@dataclass
class GatewayResult:
    """Everything needed to persist a ``run_result`` row."""

    model_id: str
    parsed: BaseModel | None
    valid: bool
    usage: NormalizedUsage
    cost: EstimatedCost
    latency_ms: int
    retries: int = 0
    raw_response: dict[str, Any] | None = None
    usage_raw: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    structured_method: str | None = None
    endpoint: str | None = None
    skipped: bool = False
    skip_reason: str | None = None
    adapter_notes: dict[str, Any] = field(default_factory=dict)
    # What was actually sent to the model (persisted for full reproducibility).
    prompt_system: str | None = None
    prompt_instruction: str | None = None
    prompt_version: str | None = None
    document_count: int = 0


class ModelGateway:
    """Provider-agnostic gateway. One instance is reusable across calls."""

    def __init__(self, *, region: str | None = None, trace: bool = True) -> None:
        self.settings = get_settings()
        self.region = region
        if trace:
            # Idempotent; no-op when Langfuse keys are absent.
            from app.observability import enable_langfuse

            enable_langfuse()

    # ------------------------------------------------------------------ public
    async def structured(
        self,
        *,
        model_id: str,
        system: str,
        instruction: str,
        schema: type[T],
        documents: list[DocumentInput] | None = None,
        config: dict[str, Any] | None = None,
        prompt_version: str | None = None,
    ) -> GatewayResult:
        """Run a structured-output call through the model-agnostic pipeline."""
        capability = get_capability(model_id)
        documents = documents or []
        config = config or {}

        # 1. capability gate (text-only model on image task -> skipped, not failed).
        adapter = get_adapter(capability)
        try:
            normalized = adapter.normalize(
                system=system,
                instruction=instruction,
                documents=documents,
                config=config,
            )
        except CapabilityGateError as gate:
            logger.warning("model %s gated out; no LLM call made: %s", model_id, gate.reason)
            return GatewayResult(
                model_id=model_id,
                parsed=None,
                valid=False,
                usage=NormalizedUsage(),
                cost=_zero_cost(),
                latency_ms=0,
                skipped=True,
                skip_reason=gate.reason,
                structured_method=capability.structured_method.value,
                prompt_system=system,
                prompt_instruction=instruction,
                prompt_version=prompt_version,
                document_count=len(documents),
            )

        messages = [
            {"role": "system", "content": normalized.system},
            {"role": "user", "content": normalized.content},
        ]

        # 2. structured call (+ repair ladder for weak models), traced by Langfuse.
        from app.observability import trace_call

        start = time.perf_counter()
        with trace_call(
            f"gateway.structured:{schema.__name__}",
            model=model_id,
            metadata={"schema": schema.__name__, "documents": len(documents)},
        ) as span:
            result = await self._call_with_fallback(
                capability=capability,
                messages=messages,
                schema=schema,
                config=config,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)

            # 3. usage + cost.
            usage = normalize_usage(result.usage_raw)
            cost = estimate_cost(
                pricing_ref=capability.pricing_ref, usage=usage, region=self.region
            )
            if span is not None:
                try:
                    span.update(
                        usage_details={
                            "input": usage.input_tokens,
                            "output": usage.output_tokens,
                            "total": usage.total_tokens,
                        },
                        metadata={
                            "valid": result.parsed is not None,
                            "cost_usd": float(cost.total_usd),
                            "latency_ms": latency_ms,
                            "retries": result.retries,
                        },
                    )
                except Exception:  # noqa: BLE001 — never let tracing break the call
                    pass

        return GatewayResult(
            model_id=model_id,
            parsed=result.parsed,
            valid=result.parsed is not None,
            usage=usage,
            cost=cost,
            latency_ms=latency_ms,
            retries=result.retries,
            raw_response=result.raw_response,
            usage_raw=to_jsonable(result.usage_raw),
            error=result.error,
            structured_method=capability.structured_method.value,
            endpoint=self.region or "default",
            adapter_notes=normalized.notes,
            prompt_system=normalized.system,
            prompt_instruction=instruction,
            prompt_version=prompt_version,
            document_count=len(documents),
        )

    # ------------------------------------------------------------------ internals
    async def _call_with_fallback(
        self,
        *,
        capability: ModelCapability,
        messages: list[dict[str, Any]],
        schema: type[T],
        config: dict[str, Any],
    ) -> _CallOutcome:
        """Structured call; on failure, fall back to free-text generation + JSON repair."""
        # --- Tier 1: Instructor structured output ---
        try:
            parsed, raw, usage_raw = await self._instructor_call(
                capability=capability, messages=messages, schema=schema, config=config
            )
            return _CallOutcome(parsed=parsed, raw_response=raw, usage_raw=usage_raw, retries=0)
        except ProviderAuthError:
            raise
        except Exception as exc:  # noqa: BLE001 - any SO failure triggers the ladder
            self._raise_provider_auth_error(capability, exc)
            logger.warning(
                "structured call failed for %s (%s); engaging repair ladder",
                capability.model_id,
                exc.__class__.__name__,
            )
            structured_error = {"stage": "structured", "type": exc.__class__.__name__, "message": str(exc) or exc.__class__.__name__}

        if not capability.needs_repair_fallback:
            # Strong, verified models: surface the structured error rather than guess.
            return _CallOutcome(parsed=None, error=structured_error, retries=1)

        # --- Tier 2: free-text generation -> robust JSON extraction -> schema validation ---
        try:
            text, raw, usage_raw = await self._freetext_call(
                capability=capability, messages=messages, schema=schema, config=config
            )
            parsed = _repair_to_schema(text, schema)
            if parsed is not None:
                return _CallOutcome(
                    parsed=parsed, raw_response=raw, usage_raw=usage_raw, retries=2
                )
            error = {**structured_error, "stage": "repair", "message": "no parseable JSON in free text"}
            return _CallOutcome(parsed=None, raw_response=raw, usage_raw=usage_raw, error=error, retries=2)
        except ProviderAuthError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("free-text fallback failed for %s: %s", capability.model_id, exc.__class__.__name__)
            return _CallOutcome(
                parsed=None,
                error={**structured_error, "stage": "fallback", "type": exc.__class__.__name__},
                retries=2,
            )

    async def _instructor_call(
        self,
        *,
        capability: ModelCapability,
        messages: list[dict[str, Any]],
        schema: type[T],
        config: dict[str, Any],
    ) -> tuple[T, dict[str, Any], Any]:
        litellm.drop_params = True

        async def acompletion_wrapper(*args, **kwargs):
            if "mode" in kwargs:
                kwargs.pop("mode")
            try:
                return await litellm.acompletion(*args, **kwargs)
            except Exception as exc:
                self._raise_provider_auth_error(capability, exc)
                raise

        mode_str = _MODE_BY_METHOD[capability.structured_method]
        if capability.structured_method == StructuredMethod.json_mode and (
            capability.model_id.startswith("vertex_ai/")
            or capability.provider.value in ("vertex_ai", "vertex_partner")
        ):
            mode_str = "MD_JSON"

        mode = getattr(instructor.Mode, mode_str)
        client = instructor.from_litellm(acompletion_wrapper, mode=mode)

        parsed, completion = await client.chat.completions.create_with_completion(
            model=capability.transport_model,
            messages=messages,
            response_model=schema,
            mode=mode,
            max_retries=config.get("max_retries", 2),
            **self._provider_kwargs(capability, config),
        )
        raw = _completion_to_dict(completion)
        usage_raw = getattr(completion, "usage", None)
        return parsed, raw, usage_raw

    async def _freetext_call(
        self,
        *,
        capability: ModelCapability,
        messages: list[dict[str, Any]],
        schema: type[T],
        config: dict[str, Any],
    ) -> tuple[str, dict[str, Any], Any]:
        """Plain completion asking for JSON conforming to the schema (no Instructor)."""
        import litellm

        schema_json = json.dumps(schema.model_json_schema())
        repair_messages = list(messages)
        repair_messages.append(
            {
                "role": "system",
                "content": (
                    "Respond with ONLY a single JSON object conforming exactly to this JSON "
                    f"schema. No prose, no code fences.\n\nSCHEMA:\n{schema_json}"
                ),
            }
        )
        try:
            completion = await litellm.acompletion(
                model=capability.transport_model,
                messages=repair_messages,
                **self._provider_kwargs(capability, config),
            )
        except Exception as exc:
            self._raise_provider_auth_error(capability, exc)
            raise
        text = completion.choices[0].message.content or ""
        return text, _completion_to_dict(completion), getattr(completion, "usage", None)

    def _provider_kwargs(self, capability: ModelCapability, config: dict[str, Any]) -> dict[str, Any]:
        """Provider-specific kwargs (Vertex creds, xAI/openai-compat keys, temperature, thinking)."""
        default_temperature = 1.0 if capability.thinking == "level" else 0.0
        kwargs: dict[str, Any] = {
            "temperature": config.get("temperature", default_temperature)
        }
        if (mot := config.get("max_output_tokens")) is not None:
            kwargs["max_tokens"] = mot
        if (to := config.get("timeout_s")) is not None:
            kwargs["timeout"] = float(to)

        provider = capability.provider.value

        # Vertex AI + Vertex Model Garden partners both route through the vertex_ai transport
        # using the same service-account credentials. (Partner model ids carry the publisher
        # prefix, e.g. vertex_ai/zai-org/glm-5-maas, and LiteLLM dispatches them as partner.)
        if provider in ("vertex_ai", "vertex_partner"):
            creds = (
                os.environ.get("GOOGLE_CLOUD_CREDENTIALS_JSON")
                or os.environ.get("SUPERCLAIMS_GOOGLE_CREDENTIALS_JSON")
            )
            project = (
                self.settings.vertexai_project
                or os.environ.get("SUPERCLAIMS_GOOGLE_PROJECT_ID")
                or os.environ.get("GOOGLE_CLOUD_PROJECT")
            )
            if creds:
                kwargs["vertex_credentials"] = creds
            if project:
                kwargs["vertex_project"] = project
            kwargs["vertex_location"] = (
                self.region or capability.vertex_location or self.settings.vertexai_location
            )

        elif provider == "xai":
            if key := os.environ.get("XAI_API_KEY"):
                kwargs["api_key"] = key

        elif provider == "openai_compatible":
            # External OpenAI-compatible endpoints (z.ai GLM, Moonshot Kimi). Resolve a key +
            # base_url from env by family; absent -> the call fails and the model stays gated.
            key_env = capability.api_key_env or "OPENAI_COMPATIBLE_API_KEY"
            base_env = capability.base_url_env or "OPENAI_COMPATIBLE_BASE_URL"
            if key := os.environ.get(key_env) or getattr(
                self.settings, key_env.lower(), None
            ):
                kwargs["api_key"] = key
            if base := os.environ.get(base_env) or getattr(
                self.settings, base_env.lower(), None
            ):
                kwargs["api_base"] = base

        elif provider == "openrouter":
            # OpenRouter fronts many upstream vendors behind one OpenAI-compatible gateway.
            # LiteLLM's ``openrouter/`` transport prefix already knows the base URL; we only
            # inject the key (``OPENROUTER_API_KEY``). Absent -> the call fails and the model
            # stays gated. Its own provider (not ``openai_compatible``) so the UI segregates it.
            key_env = capability.api_key_env or "OPENROUTER_API_KEY"
            if key := os.environ.get(key_env) or getattr(
                self.settings, key_env.lower(), None
            ):
                kwargs["api_key"] = key

        elif provider == "bedrock":
            access_key = self.settings.aws_access_key_id or os.environ.get(
                "AWS_ACCESS_KEY_ID"
            )
            secret_key = self.settings.aws_secret_access_key or os.environ.get(
                "AWS_SECRET_ACCESS_KEY"
            )
            token = self.settings.aws_bearer_token_bedrock or os.environ.get(
                "AWS_BEARER_TOKEN_BEDROCK"
            )

            if access_key and secret_key:
                kwargs["aws_access_key_id"] = access_key
                kwargs["aws_secret_access_key"] = secret_key
                # Remove any stale ambient bearer token from os.environ so LiteLLM doesn't
                # attempt to use an expired static bearer token instead of IAM SigV4 signing.
                os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
            elif token:
                kwargs["api_key"] = token
            else:
                raise ProviderAuthError(
                    "bedrock credentials missing — set AWS_ACCESS_KEY_ID & AWS_SECRET_ACCESS_KEY or AWS_BEARER_TOKEN_BEDROCK in .env"
                )

            kwargs["aws_region_name"] = self.region or capability.default_region or self.settings.aws_region_name
            # Bedrock on-demand throughput quotas are low by default; retry 429s/throttling
            # with exponential backoff instead of failing the run immediately.
            kwargs["num_retries"] = config.get("num_retries", 5)
            kwargs["retry_strategy"] = "exponential_backoff_retry"

        # Reasoning/thinking budget (provider-agnostic LiteLLM param) when requested + supported.
        if capability.thinking == "level" and (
            level := config.get("thinking_level")
        ) is not None:
            kwargs["reasoning_effort"] = level
        elif (
            capability.thinking
            and provider not in {"vertex_ai", "vertex_partner"}
            and (budget := config.get("thinking_budget")) is not None
        ):
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": int(budget)}

        return kwargs

    @staticmethod
    def _raise_provider_auth_error(capability: ModelCapability, exc: Exception) -> None:
        """Translate an expired Bedrock bearer token or auth error without leaking provider details."""
        if capability.provider.value != "bedrock":
            return
        message = str(exc).lower()
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        if (
            "bedrock credentials missing" in message
            or "bedrock token missing" in message
        ):
            raise ProviderAuthError(
                "bedrock credentials missing — set AWS_ACCESS_KEY_ID & AWS_SECRET_ACCESS_KEY or AWS_BEARER_TOKEN_BEDROCK in .env"
            ) from exc
        if (
            "bedrock token expired" in message
            or "expiredtoken" in message
            or (status in {401, 403} and "expired" in message and "token" in message)
        ):
            raise ProviderAuthError(
                "bedrock token expired — configure AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env for continuous auto-renewal"
            ) from exc


# ---------------------------------------------------------------------------- helpers
@dataclass
class _CallOutcome:
    parsed: BaseModel | None = None
    raw_response: dict[str, Any] | None = None
    usage_raw: Any | None = None
    error: dict[str, Any] | None = None
    retries: int = 0


def _completion_to_dict(completion: Any) -> dict[str, Any]:
    if completion is None:
        return {}
    if hasattr(completion, "model_dump"):
        try:
            return completion.model_dump()
        except Exception:
            pass
    return to_jsonable(completion)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _repair_to_schema(text: str, schema: type[T]) -> T | None:
    """Robustly extract a JSON object from free text and validate against ``schema``.

    Mirrors the audit agent's degenerate-output repair: strip code fences, find the outermost
    balanced ``{...}``, then validate. Returns ``None`` if nothing validates.
    """
    if not text:
        return None
    candidates: list[str] = []

    fenced = _FENCE_RE.findall(text)
    candidates.extend(fenced)
    candidates.append(text)

    # outermost balanced object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for cand in candidates:
        cand = cand.strip()
        if not cand:
            continue
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        try:
            return schema.model_validate(data)
        except ValidationError:
            continue
    return None


def _zero_cost() -> EstimatedCost:
    z = Decimal("0")
    return EstimatedCost(z, z, z, z, z, "n/a", None)

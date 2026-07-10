# 04 — Workstream B: Providers (AWS Bedrock · Qwen3-VL-8B · Gemini 3.1 Pro)

> Prerequisites: read `00-master-plan.md` (esp. §6.6 env vars, §6.7 model ids, §8 risks) and
> `01-context-colosseum.md` §3 (provider layer). You do NOT create migrations.

## Goal

Make three new model sources callable through the existing `ModelGateway.structured()`:
1. **AWS Bedrock** via bearer-token API key (region ap-south-1) — multiple models.
2. **Qwen3-VL-8B** self-deployed on vLLM (OpenAI-compatible) — vision model for document tasks.
3. **Gemini 3.1 Pro** on Vertex (judge default; currently gated because the wrong project
   was tried) — verify against the superclaims-ai project and enable.

## Facts you need

- Gateway: `backend/app/providers/gateway.py` — LiteLLM + Instructor under the hood.
  `_provider_kwargs(capability)` (~:308) is where per-provider call kwargs (keys, base_url,
  vertex creds) are injected. `_MODE_BY_METHOD` maps `structured_method` → Instructor mode.
- Capabilities: `backend/app/providers/capabilities.py` — `Providers` enum currently
  `vertex_ai | vertex_partner | xai | openai_compatible`. Frozen `ModelCapability`.
- Catalog: `backend/app/providers/catalog/*.yaml`, loaded by `registry.py` at import. Look
  at `gemini.yaml` and `qwen.yaml` for the exact YAML shape (id, litellm_model, provider,
  modalities, pdf_native, vision, size caps, structured_method, needs_repair_fallback,
  thinking, pricing_ref, enabled, verified, notes).
- Adapters select by capability: `pdf_native` → GeminiVertexAdapter, `vision` →
  RasterizingAdapter (PDF→images), text-only → TextOnlyAdapter. **No adapter code changes
  needed** for either new provider.
- Pricing: `providers/pricing/rate_card.json` keyed by `pricing_ref`.
- Env (contract 00 §6.6): `AWS_BEARER_TOKEN_BEDROCK` (presigned, **expires ~12h**),
  `AWS_REGION_NAME=ap-south-1`, `QWEN_VL_BASE_URL=http://15.252.27.168:8000/v1`,
  `QWEN_VL_API_KEY=EMPTY`. LiteLLM natively supports `bedrock/<model_id>` and reads
  `AWS_BEARER_TOKEN_BEDROCK` + `AWS_REGION_NAME` from env (verify against the installed
  litellm version in `uv.lock`; if the installed version predates bearer-token support,
  bump litellm in `pyproject.toml`).

## Deliverables

| File | Action |
|---|---|
| `backend/app/providers/capabilities.py` | add `bedrock` to Providers enum |
| `backend/app/providers/gateway.py` | `_provider_kwargs`: `bedrock` branch — pass `aws_region_name`, ensure bearer token env is set (fail with clear error if missing/expired); `openai_compatible` branch already passes base_url/key — confirm it reads per-model `base_url` from capability (qwen entry uses `QWEN_VL_BASE_URL`) |
| `backend/app/providers/catalog/bedrock.yaml` | NEW — model entries (see below) |
| `backend/app/providers/catalog/qwen.yaml` | add `qwen3-vl-8b` entry |
| `backend/app/providers/catalog/gemini.yaml` | un-gate `gemini-3.1-pro` (+ optionally gemini-3-flash) after verification |
| `backend/app/providers/pricing/rate_card.json` | add pricing_refs: bedrock models (per-1M token rates from AWS pricing), `qwen3-vl-8b` self-deploy (rate 0, VM-uptime convention) |
| `backend/app/core/config.py` | add settings: `aws_bearer_token_bedrock`, `aws_region_name`, `qwen_vl_base_url`, `qwen_vl_api_key` |
| `.env.example` | add the four vars with the expiry comment (contract 00 §6.6) |
| `scripts/verify_bedrock.py` | NEW — list + smoke-test Bedrock models |
| `scripts/verify_model.py` | NEW — generic single-model live check (used by `POST /api/catalog/{id}/verify` in WS E) |
| `backend/tests/test_bedrock_catalog.py`, `test_qwen_vl.py` | NEW — offline tests (capability gating, kwargs construction; live tests marked `@pytest.mark.live`) |
| `docs/models-and-caveats.md` | append Bedrock + Qwen3-VL sections (caveats, token expiry) |

## Design details

### 1. Bedrock

- `scripts/verify_bedrock.py`:
  1. `GET` foundation-model list via `boto3 bedrock` client if available, else direct HTTPS
     `https://bedrock.ap-south-1.amazonaws.com/foundation-models` with
     `Authorization: Bearer $AWS_BEARER_TOKEN_BEDROCK`.
  2. For each candidate model (or `--model <id>`), attempt a 1-token
     `litellm.completion(model=f"bedrock/{model_id}", …)` and report ok/error.
  3. Print a ready-to-paste YAML snippet for the verified ones. Exit non-zero on expired
     token with the message "AWS_BEARER_TOKEN_BEDROCK expired — refresh it in .env".
- `catalog/bedrock.yaml`: seed entries **gated (enabled=false, verified=false)** for the
  likely families — Anthropic Claude (e.g. `bedrock-claude-sonnet-4-5` →
  `bedrock/apac.anthropic.claude-sonnet-4-5-…` inference profile id as reported by the
  list call), Amazon Nova (pro/lite/micro), Meta Llama, Mistral. Flip
  `enabled/verified: true` ONLY for models the verify script confirms. Capabilities:
  Claude/Nova → `vision: true, pdf_native: false` (RasterizingAdapter), structured_method
  `tools` for Claude, `json_mode` for Nova/Llama/Mistral with
  `needs_repair_fallback: true` for the weaker ones. Use ap-south-1 inference-profile ids
  (`apac.` prefix) where the raw model id is not directly invocable.
- Token expiry UX: gateway raises `ProviderAuthError("bedrock token expired — refresh
  AWS_BEARER_TOKEN_BEDROCK in .env")` when the underlying call returns
  401/403 ExpiredToken; runs record it as cell error, not a crash.

### 2. Qwen3-VL-8B

Catalog entry in `qwen.yaml`:

```yaml
- id: qwen3-vl-8b
  litellm_model: openai/Qwen/Qwen3-VL-8B-Instruct
  provider: openai_compatible
  base_url_env: QWEN_VL_BASE_URL        # follow the existing per-model base_url pattern;
  api_key_env: QWEN_VL_API_KEY          # if none exists, add these two keys and read them
  modalities: [text, image]             # in _provider_kwargs for openai_compatible
  pdf_native: false
  vision: true
  max_image_mb: 10
  max_payload_mb: 25
  structured_method: json_mode          # vLLM supports OpenAI json_schema via guided
  needs_repair_fallback: true           # decoding on recent versions — try json_schema
  thinking: false                       # first in verify script; fall back to json_mode.
  pricing_ref: self_deploy_qwen3_vl_8b  # rate 0 (self-hosted)
  enabled: true
  verified: false                       # flip after live check
  notes: "vLLM at 15.252.27.168:8000; 8B VL — expect weaker structured compliance; rasterized pages"
```

Check how existing openai_compatible entries wire base_url (open_models.yaml /
qwen.yaml + `_provider_kwargs`); reuse that mechanism rather than inventing a new one.
Live check: health `GET /v1/models`, then a rasterized single-page structured call on
`test-docs/T14SBYEU_1.pdf` via the gateway (segregation schema). Flip `verified: true` when
it returns parseable output.

### 3. Gemini 3.1 Pro (judge dependency)

- Why gated today: previous verification attempted a Vertex project without Gemini 3.x
  access (404). The **superclaims-ai** project has `gemini-3.1-pro-preview` in production
  use, and Colosseum layers `superclaims-ai/.env` via `EXTERNAL_ENV_FILES`
  (`core/config.py::_bootstrap_external_env`) — so the working project id + SA are likely
  already in the environment under that repo's var names (check `GOOGLE_CLOUD_CREDENTIALS_JSON`
  / `google_project_id` names in superclaims-ai's `.env`, and map them into
  `VERTEXAI_PROJECT` / `GOOGLE_APPLICATION_CREDENTIALS` if needed).
- `scripts/verify_model.py --model gemini-3.1-pro`: one cheap structured call
  ("return {\"ok\": true}" schema). On success set `enabled: true, verified: true` for
  `gemini-3.1-pro` (litellm_model `vertex_ai/gemini-3.1-pro-preview`) and add pricing_ref.
  Also verify `gemini-3-flash` (used widely by the reference pipelines) and enable if it
  works. Record thinking support: gemini-3.x uses `thinking_level` (minimal|low|medium) —
  confirm the gateway's thinking kwarg plumbing supports level-style (it currently sends
  budget-style); extend `_provider_kwargs` to send `thinking_level` when the capability
  declares `thinking: level` (small, contained change — coordinate with nothing else).

## Acceptance criteria

1. `uv run python scripts/verify_bedrock.py` prints per-model ok/fail and a YAML snippet;
   at least one Bedrock model verified+enabled end-to-end through
   `ModelGateway.structured()` on a rasterized test PDF.
2. `qwen3-vl-8b` runs segregation on a test PDF through the gateway (repair fallback
   allowed) and appears in `list_models(enabled_only=True)`.
3. `gemini-3.1-pro` verified via the superclaims project; a structured smoke call succeeds;
   thinking_level plumbing works (call with level=low logged in request).
4. Offline tests pass without any network (`pytest -m "not live"`); live tests behind
   `-m live`.
5. No secret values in any committed file (`git grep` for the token prefix must be empty);
   `.env.example` documents everything incl. expiry/refresh.
6. `docs/models-and-caveats.md` updated.

## Risks

- Bearer token expiry (~12h) — every failure path must say so explicitly.
- ap-south-1 model availability differs from us-east-1; the list call is the source of truth.
- vLLM guided-decoding support depends on server version — degrade to json_mode + repair.
- If litellm version bump is required, run the full existing test suite (`uv run pytest`)
  to catch regressions in the Vertex/xai paths.

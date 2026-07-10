# Colosseum — Model Catalog & Caveats

> Companion docs: [project-overview.md](./project-overview.md) and [plan.md](./plan.md).
>
> **This is the source of truth for the in-code capability registry**
> (`backend/app/providers/registry.py` + `capabilities.py`). The registry is generated to
> match this doc; they must never drift. Cells marked **(verify)** MUST be confirmed live
> against the current provider docs by the build agent before shipping a capability flag —
> **do not ship unverified flags.** Research date: June 2026.

## Capability profile (fields the registry tracks per model)

- `provider` — e.g. `vertex_ai`, `vertex_partner`, `xai`, `openai_compatible`, `bedrock`.
- `access` — `maas` (managed/serverless) | `self_deploy` (GPU/TPU endpoint).
- `modalities` — text / image / pdf / audio / video.
- `pdf_native` — model ingests PDF directly (true) vs needs rasterization to images (false).
- `vision` — accepts image input.
- `max_image_mb` / `max_payload_mb` / `max_image_megapixels` / `image_formats`.
- `context_window` — input token budget.
- `structured_method` — `json_schema` | `json_mode` | `tools` (+ whether repair fallback needed).
- `thinking` — supports reasoning/thinking budget or level; reasoning tokens billed.
- `caching` — prompt/context caching supported.
- `batch` — batch API available.
- `pricing_ref` — key into the rate card (input/output/cache/thinking $ per 1M tokens).

## Access patterns (Vertex AI Model Garden)

Model Garden (now under "Gemini Enterprise Agent Platform", formerly Vertex AI) exposes 200+
models in **two access patterns**, both routable via LiteLLM's `vertex_ai` / `vertex_partner`
providers:

1. **MaaS — managed, serverless, OpenAI-compatible endpoint.** No infra to run. Gemini,
   Claude (Anthropic), Mistral, DeepSeek, Qwen, gpt-oss, etc.
2. **Self-deploy — you provision a GPU/TPU endpoint** (vLLM container). Gemma, Llama, and open
   models. Caveats: you choose hardware/region/replicas; **scale-to-zero returns HTTP 429 on
   cold start** while replicas spin up; **the endpoint bills on VM uptime even when idle.**
   Treat as opt-in/advanced in Colosseum.

**Cross-cutting Vertex caveat:** request payloads are capped at **30 MB**. Large PDFs / many
images hit this *before* the token limit, so the adapter must measure encoded payload size and
page-split or compress.

## Seed caveats table

| Model / family | Provider / access | Vision | PDF | Structured output | Context | Thinking / Cache | Key caveats |
|---|---|---|---|---|---|---|---|
| Gemini 3.x (3.1 Pro, 3 Flash, 3 Flash-Lite) | vertex_ai / MaaS | yes | **native** | json_schema | ~1M | thinking levels / cache | 30 MB payload cap |
| Gemini 2.5 (Pro/Flash/Flash-Lite) | vertex_ai / MaaS | yes | **native** | json_schema | ~1M | thinking budget / cache | 30 MB payload cap |
| Claude (Opus 4.7 / Sonnet 4.6) | vertex_partner / MaaS | yes | **native** | tools / json | large | yes / prompt caching | **+10% regional/multi-region premium**; 30 MB cap; citations, tool use |
| Mistral (e.g. Small 3.1) | vertex_partner / MaaS | yes | via image | json mode | 128k | — | multimodal; verify SO method **(verify)** |
| DeepSeek R1 | vertex_partner / MaaS | **no** | **no** | json mode **(verify)** | large | reasoning tokens | **text-only → gate out of image/PDF tasks** |
| DeepSeek V3.2 | vertex_partner / MaaS | **(verify)** | via image **(verify)** | json mode **(verify)** | large | reasoning tokens | confirm modality before image tasks |
| Qwen3 / Qwen3-Coder | vertex_partner / MaaS | **VL only** | via image | json / tools **(verify)** | large | — | base Qwen3 text-only; use VL variant for vision |
| Gemma 3 | self_deploy | text (3), — | via image | json (weak) **(verify)** | — | — | cold-start 429; VM-uptime cost |
| Gemma 4 (26B MoE) | MaaS + self_deploy | yes (multimodal) | via image | json (weak) **(verify)** | — | — | managed/serverless available; weak SO reliability |
| Grok 4.x (xAI) | xai / external | yes | via image | json / tools **(verify)** | large | thinking variants | **base64 image ≤4 MB**, URL ≤20 MB, **≤33 MP**, **jpg/png only**, tile-based image token billing (~256 tok/tile, ≤6 tiles) |
| GLM 5.x | openai_compatible / external | **VL only (verify)** | via image | **(verify)** | large | **(verify)** | verify modality + SO reliability |
| Kimi K2.x | openai_compatible / external | yes **(verify)** | via image | **(verify)** | long | **(verify)** | verify SO reliability |
| Llama (open) | self_deploy / vertex / external | varies by variant | via image | json **(verify)** | varies | — | cold-start 429 if self-deployed; pick instruct/vision variant deliberately |

## Per-model caveat notes (expand as verified)

- **Grok (xAI) vision** — base64 images capped at **4 MB** (use image URL for up to 20 MB);
  resolution cap **~33 MP**; formats **jpg/jpeg/png only**. Images tiled into 448×448 blocks at
  ~256 tokens/tile, max 6 tiles (+1) → <1,792 tokens/image. **PDFs must be rasterized to images
  per page** and each page kept under the cap (downscale/compress; split if needed).
- **Gemini** — ingests PDF natively as a file part
  (`{"type":"file","mime_type":"application/pdf","base64":...}`); honor the **30 MB** Vertex
  payload cap by selecting only relevant pages (see `extract_pages_as_base64` in superclaims-ai).
- **Claude on Vertex** — full vision + native PDF + prompt caching + tool use + citations;
  **regional/multi-region endpoints add ~10% over global pricing** — record which endpoint a
  run used so cost comparisons stay fair.
- **DeepSeek R1** — **text-only**; the capability gate must **skip image/PDF tasks** for it
  (don't send rasterized pages and call it a fair comparison — record it as "not applicable").
- **Self-deploy models (Gemma/Llama)** — first request after scale-to-zero may return **429**
  while replicas start; the runner should retry with backoff and **not** count cold-start
  latency as model latency. Endpoint **bills on VM uptime**, so cost accounting differs from
  per-token MaaS.

## Pricing

Seed the rate card from `superclaims-ai/backend/app/lang_graph/pricing/vertex_rate_card.json`
(Gemini list prices per 1M tokens) and **extend to multi-provider + a `thinking`/reasoning
rate** and a `cache_read` rate. Record `pricing_version` on every run. For self-deploy models,
cost is VM-uptime-based, not per-token — track separately.

## How to extend this catalog

1. Add the model to the right `backend/app/providers/catalog/<family>.yaml` (grouped
   `family -> version -> variant`), with its provider, access pattern, capability flags, and
   `enabled`/`verified`/`reason`.
2. Verify availability **live** before flipping `enabled=true` (callable on this project's
   Vertex, or a working external key). Until then it ships `enabled=false` with a `reason`.
3. Add/seed the pricing entry in `providers/pricing/rate_card.json` (input/output/cache/thinking
   per 1M; mark unknowns; bump `pricing_version`).
4. The registry (`registry.py`) loads the catalog automatically — no code change needed.
5. The runner appends **measured** facts (observed token classes, structured-output success
   rate, failures, real latency) so the catalog reflects reality, not just docs.

---

# Phase 2 — Exhaustive, versioned Model Garden catalog

The capability registry is now **data-driven**: `backend/app/providers/catalog/*.yaml`
(one file per family, grouped `family -> version -> variant`) is the single source loaded by
`providers/registry.py`. Thinking vs non-thinking are **first-class separate configs** (e.g.
`grok-4.20-reasoning` vs `grok-4.20-non-reasoning`, `qwen3-next-...-thinking` vs `...-instruct`).

**Enumeration sources (June 2026):** LiteLLM's `vertex_ai` / `vertex_partner` provider model
lists (authoritative for what routes through the Vertex transport), the xAI provider list, and
the external z.ai / Moonshot catalogs — cross-checked per family. `gcloud ai model-garden
models list` was **not available** in this environment (no `gcloud`), so Model-Garden
*enablement* on this project could not be confirmed from the CLI; consequently **every
partner/external model ships `enabled=false, verified=false` with a `reason`** and is only
flipped on after a live call succeeds.

## Availability gating (what is enabled vs gated off)

Updated by the **July 2026 re-verification probe** (`scripts/verify_model.py`, one live
structured-output call per family) on `vertex-internal-testing`. Supersedes the Phase 2.5 probe
(June 19 2026) numbers below for every family that was re-tested.

- **ENABLED + VERIFIED (Vertex MaaS, `vertex_partner`), confirmed callable July 2026:**
  - **Gemini 2.5 / 3.x** — full family (native PDF, vision, `json_schema`, thinking, caching).
  - **DeepSeek R1** — `deepseek-ai/deepseek-r1-0528-maas` (text-only reasoning).
  - **Qwen3** — full family incl. Coder/Next, plus self-deployed **Qwen3-VL-8B**.
  - **Gemma 4 26B** — MaaS multimodal.
  - **GLM-5 / GLM-4.7** — Vertex MaaS, `vertex_ai/zai-org/*-maas`. **Global-endpoint-only**
    (`vertex_location: global`) — the `us-central1` default 400s with `FAILED_PRECONDITION`.
  - **Grok 4.20 / 4.1-fast (reasoning + non-reasoning)** — Vertex MaaS, `vertex_ai/xai/*`.
    **Global-endpoint-only**, same fix as GLM.
  - **Kimi K2 Thinking** — `vertex_ai/moonshotai/kimi-k2-thinking-maas`. **Global-endpoint-only**.
  - **gpt-oss 120B / 20B** — `vertex_ai/openai/gpt-oss-*-maas`. Both answered *and* parsed to
    schema cleanly on this probe (the earlier "callable but weak structured output" note for
    120b did not reproduce — retest if it resurfaces).
  - **MiniMax M2** — `vertex_ai/minimaxai/minimax-m2-maas`. **Global-endpoint-only**.

  The common fix across GLM/Grok/Kimi/MiniMax: these Model Garden partner deployments only exist
  at Vertex's `global` endpoint, not the project's default `us-central1` region. The catalog
  previously had no `vertex_location` override for these families, so the gateway sent requests
  to `us-central1` and got a hard `400 FAILED_PRECONDITION`/`404` — indistinguishable from "not
  enabled" without reading the error body. Adding `vertex_location: global` to each group (or
  per-model for MiniMax, since its Jamba group-mates are regional) fixed all four families with
  no credential changes.

- **STILL GATED OFF (`enabled=false`) — genuine 404s, not a config issue:**
  - **Claude** (all 13 Vertex MaaS variants) — `404 NOT_FOUND` on
    `publishers/anthropic/models/claude-haiku-4-5@20251001` (and presumably siblings): Anthropic
    Model Garden is not enabled/accepted for the `vertex-internal-testing` GCP project. This is a
    GCP Console / Model Garden acceptance step, not something fixable from this repo.
  - **Llama** (all 11 variants) — same 404 pattern on `publishers/meta/models/...`: Llama Model
    Garden not enabled on this project.
  - **Mistral** (all 6 variants) — same 404 pattern on `publishers/mistralai/models/...`.
  - **AI21 Jamba 1.5** (large/mini) — same 404 pattern on `publishers/ai21/models/...`.
  - For all four: re-run `uv run python scripts/verify_model.py --model <id>` after enabling the
    corresponding Model Garden publisher in the GCP Console for `vertex-internal-testing` (or
    switching `VERTEXAI_PROJECT` to a project where they're already enabled).
  - External-only endpoints (z.ai GLM, Moonshot Kimi, xAI Grok direct): *"no API key (only
    Vertex + Langfuse creds present)"* — registered under `openai_compatible` / `xai`,
    disabled until a key is supplied. (Their Vertex MaaS equivalents above are the ones that
    now work.)
  - Self-deploy (Gemma 3): *"self-deploy endpoint not provisioned"* — **VM-uptime priced**, not
    per-token; cold-start 429 on first call.
  - **AWS Bedrock** (all 6 models): `AWS_BEARER_TOKEN_BEDROCK` is set in `.env` but currently
    returns `403 Forbidden` from `scripts/verify_bedrock.py` (both the boto3 path, which raises
    `NoCredentialsError` since bearer-token-only auth isn't understood by the installed botocore,
    and the direct-HTTPS bearer-token fallback, which gets a real 403). The token has very likely
    expired — it's documented as lasting ~12 hours. Needs a fresh token in `.env` before Bedrock
    can be re-verified; not fixable from the codebase alone.

## Families & versions registered (counts)

| Family | Provider route | Versions / variants registered | Enabled |
|---|---|---|---|
| **gemini** | `vertex_ai` (MaaS) | 2.5 (flash/pro/flash-lite), 3 (flash/pro), 3.1 (pro/flash-lite), 3.5 (flash) | **8 (all)** |
| **claude** | `vertex_partner` (MaaS) | Opus 4/4.1/4.5/4.6/4.7/4.8, Sonnet 4/4.5/4.6, Haiku 4.5, 3.7/3.5 Sonnet, 3.5 Haiku | 0 (gated — Model Garden not enabled on project, 404) |
| **deepseek** | `vertex_partner` (MaaS) | R1-0528 (thinking), V3.1, V3.2, OCR (vision) | **1 (R1-0528 verified)** |
| **qwen** | `vertex_partner` (MaaS) | 3-235B, 3-coder-480B, 3-next-80B **instruct + thinking**, self-deploy VL-8B | **5 (all)** |
| **kimi** | `vertex_partner` + `openai_compatible` | K2 thinking (Vertex), K2/K2.5/K2-thinking (Moonshot) | **1 (Vertex K2 thinking, verified)** |
| **glm** | `vertex_partner` + `openai_compatible` | GLM-5, GLM-4.7 (Vertex); GLM-5/4.7/4.6/4.6V (z.ai) | **2 (Vertex GLM-5/4.7, verified)** |
| **grok** | `vertex_partner` + `xai` | 4.20 / 4.1-fast **reasoning + non-reasoning** (Vertex); 4.3, 4.20, 4-fast (r/nr), 4, 3, 3-mini (xAI) | **4 (all 4 Vertex variants, verified)** |
| **mistral** | `vertex_partner` (MaaS) | Small 3.1, Medium 3, Large, Nemo, Codestral 2, OCR | 0 (gated — Model Garden not enabled on project, 404) |
| **llama** | `vertex_partner` (MaaS) | 4 Scout/Maverick (16E/128E), 3.2-90B-Vision, 3.1 (405B/70B/8B), 3 (405B/70B/8B) | 0 (gated — Model Garden not enabled on project, 404) |
| **open_models** | `vertex_partner` (MaaS + self_deploy) | Gemma 4 26B (MaaS), Gemma 3 27B/12B/4B (self-deploy), gpt-oss 120B/20B, MiniMax M2, Jamba 1.5 large/mini | **4 (Gemma 4, gpt-oss 120B+20B, MiniMax M2 verified)** |

**Enabled and verified: 25 models** (up from 10 after the July 2026 re-verification pass — see
"Availability gating" above). Run
`python -c "from app.providers.registry import catalog_summary; print(catalog_summary())"`
for the live per-family counts.

## Per-family caveats (verified against current provider docs)

- **Claude (vertex_partner):** native PDF + vision + prompt caching + tool-use; structured
  output via TOOLS mode. **+10% regional/multi-region premium** — `run_result.endpoint` records
  the endpoint so cost comparisons stay fair.
- **DeepSeek R1 / V3.x:** **text-only** reasoning -> the capability gate **skips** them for
  image/PDF tasks (recorded "not applicable"). Only `deepseek-ocr` is vision-capable. They
  still participate fully in the **text** OPD tasks (items_categorisation, nme_analysis).
- **Qwen3 (Vertex MaaS):** the MaaS members are **text-only**; VL variants are self-deploy.
  Gated out of image tasks; full participants in text tasks. Thinking variant is separate.
- **Grok (xAI / Vertex):** **base64 image ≤4 MB** (URL ≤20 MB), **≤33 MP**, **jpg/png only**,
  tile-based image-token billing. PDFs **must** be rasterized per page (the `RasterizingAdapter`
  enforces all of this via the doc-prep toolkit). Reasoning vs non-reasoning are separate.
- **GLM / Kimi:** available on **both** Vertex MaaS (`vertex_partner`, existing creds) and the
  external z.ai / Moonshot APIs (`openai_compatible`, needs a key). Treated text-only for the
  document tasks (vision members listed separately); `json_mode` + repair ladder.
- **Mistral / Llama:** vision members (Small 3.1, Medium 3, OCR; Llama 4, 3.2-90B-Vision) take
  rasterized images; the rest are text-only. `json_mode` + repair ladder.
- **Gemma 4 (MaaS) / Gemma 3 (self-deploy):** Gemma 3 is **VM-uptime priced** (self-deploy GPU
  endpoint, cold-start 429); flagged separately in the rate card (`gemma-self-deploy`, rates 0
  with a note). Weak structured-output reliability -> repair ladder.
- **gpt-oss / MiniMax / Jamba:** text-only; gated out of image/PDF tasks.

## Adapters (Phase 2)

- `vertex_partner` is routed by **capability, not just provider**: `pdf_native` Claude uses the
  PDF pass-through adapter; vision-only Grok/Llama/Gemma/Mistral use the **`RasterizingAdapter`**
  (`pdf_to_images` -> `prepare_image_for_cap` per the 4 MB / 33 MP / jpg-png / 30 MB caps).
- `xai` and `openai_compatible` external models use the same rasterizing/text adapters; creds
  are resolved per provider (`XAI_API_KEY`, `OPENAI_COMPATIBLE_API_KEY` + `_BASE_URL`).
- Text-only models on a document task are **gated out** (recorded skipped / "not applicable",
  never failed) by the shared capability gate.

## Pricing (`providers/pricing/rate_card.json`, version `colosseum-2026-06-phase2`)

Input/output/cache-read/thinking $ per 1M for every `pricing_ref`. Estimates from public list
prices (cross-checked vs LiteLLM `model_cost` where available), **not** provider invoices.
Self-deploy (`gemma-self-deploy`) is VM-uptime priced (rates 0 + a `note`) and tracked
separately. `pricing_version` is recorded on every `run_result`.

## v2 provider additions (July 2026)

### AWS Bedrock

Bedrock calls use LiteLLM's `bedrock/` transport with `AWS_REGION_NAME=ap-south-1` and the
short-lived `AWS_BEARER_TOKEN_BEDROCK` API key. The token typically expires after about 12
hours. Missing credentials fail before a network call; an `ExpiredToken` 401/403 is reported as
`bedrock token expired — refresh AWS_BEARER_TOKEN_BEDROCK in .env`. Token values are never
stored in the catalog, results, scripts, or logs.

The seeded catalog includes Claude Sonnet 4.5, Nova Pro/Lite/Micro, Llama 3.2 90B Vision, and
Mistral Large. They intentionally remain `enabled=false, verified=false` until
`scripts/verify_bedrock.py` confirms access for the current account and region. Claude and
Nova/Llama vision inputs use rasterized PDF pages; Nova Micro and Mistral Large are text-only.
Claude uses tool-based structured output, while the other entries use JSON mode plus the repair
fallback. Claude Sonnet 4.5 uses its global inference profile because AWS documents Mumbai as a
supported source region; the verification script remains the source of truth for account-level
availability. See the [AWS model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-5.html)
and [inference-profile support](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html).

### Qwen3-VL-8B (self-deployed vLLM)

`qwen3-vl-8b` maps to `openai/Qwen/Qwen3-VL-8B-Instruct` at `QWEN_VL_BASE_URL` and uses
`QWEN_VL_API_KEY` (`none` or `EMPTY` as key). The July 2026 verification succeeded, so it is
enabled and `verified=true`. It accepts
text and rasterized page images, caps images at 10 MB and total payloads at 25 MB, and uses JSON
mode with the repair ladder because guided-decoding behavior depends on the deployed vLLM
version. Per-token catalog cost is zero; infrastructure cost is VM uptime and must be tracked
outside token pricing.

### Gemini 3.1 Pro

The stable Colosseum id `gemini-3.1-pro` maps to
`vertex_ai/gemini-3.1-pro-preview` and is the default judge model. Gemini 3.x uses level-style
thinking (`minimal`, `low`, `medium`, or `high`), which the gateway maps to LiteLLM's
`reasoning_effort`; Gemini 2.5 retains token-budget thinking. The July 2026 live probe succeeded
against the layered superclaims-ai credentials at the `global` Vertex endpoint, so this catalog
entry is enabled and verified. Level-style Gemini models default to temperature 1.0 as
recommended by the installed LiteLLM transport; explicit run configuration still wins. Google
documents Gemini 3.1 Pro as a preview multimodal model with native PDF support and a 1M-token
context window in the [Vertex AI release notes](https://cloud.google.com/vertex-ai/generative-ai/docs/release-notes).

### `EXTERNAL_ENV_FILES` — healthpay-ai path correction (July 2026)

`EXTERNAL_ENV_FILES` previously pointed at
`/Users/ekincare/superclaims/healthpay-ai/.env`, which does not exist — healthpay-ai's real env
files live at `healthpay-ai/healthpay/.env` and `healthpay-ai/healthpay/backend/.env`. Because
`_bootstrap_external_env()` (`core/config.py`) silently skips any path that doesn't exist, this
was a no-op: it never contributed credentials and never broke anything either, since
`superclaims-ai/.env` already supplies the working `vertex-internal-testing` project ID and
service-account JSON via `SUPERCLAIMS_GOOGLE_PROJECT_ID` / `SUPERCLAIMS_GOOGLE_CREDENTIALS_JSON`.
Fixed to point at `healthpay-ai/healthpay/backend/.env`. That file uses generic (unprefixed) key
names (`GOOGLE_API_KEY`, `GOOGLE_CLOUD_CREDENTIALS_JSON`, etc.) rather than a
`HEALTHPAY_`-prefixed set, and since `_bootstrap_external_env()` never overwrites a key already
supplied by Colosseum's own `.env` or by an earlier file in `EXTERNAL_ENV_FILES`, layering it in
is additive/safe — it does not change which Vertex project or credentials Colosseum actually
uses today (still `vertex-internal-testing` via superclaims-ai). No evidence was found anywhere
in the repo of a distinct "healthpay-ai" GCP project or Vertex credential; healthpay-ai's role in
this repo is otherwise limited to vendored reference prompts/schemas (see
`backend/app/tasks/prompts/*healthpay*.py`), not live Vertex traffic.

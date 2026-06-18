# Colosseum — Model Catalog & Caveats

> Companion docs: [project-overview.md](./project-overview.md) and [plan.md](./plan.md).
>
> **This is the source of truth for the in-code capability registry**
> (`backend/app/providers/registry.py` + `capabilities.py`). The registry is generated to
> match this doc; they must never drift. Cells marked **(verify)** MUST be confirmed live
> against the current provider docs by the build agent before shipping a capability flag —
> **do not ship unverified flags.** Research date: June 2026.

## Capability profile (fields the registry tracks per model)

- `provider` — e.g. `vertex_ai`, `vertex_partner`, `xai`, `openai_compatible`.
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

1. Add a row here with the model's provider, access pattern, and caveats (mark unknowns
   **(verify)**).
2. Verify each **(verify)** cell live against the provider's current docs.
3. Add/seed the pricing entry in the rate card.
4. Regenerate / update the in-code capability registry to match this row.
5. The runner appends **measured** facts (observed token classes, structured-output success
   rate, failures, real latency) back here so the catalog reflects reality, not just docs.

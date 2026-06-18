# Colosseum — Project Overview

> Companion docs: [plan.md](./plan.md) (build plan) and
> [models-and-caveats.md](./models-and-caveats.md) (model catalog + caveats).

## What Colosseum is

Colosseum is a **permanent, model-agnostic LLM benchmarking & evaluation platform** for
health-claims document processing. It runs the **same prompts**, **same sample documents**,
and **same mandatory structured-output schemas** across **many models and providers**, then
tells us — objectively — **which model is the most cost-efficient for each task**.

It is a "plug-and-play model arena": add a model + provider, and the same battery of tasks
runs against it automatically, with every input, output, token class, latency, and cost
captured and compared.

## The long-term goal

A durable internal platform that lets us, at any point:

1. **Drop in any new model** (a new Gemini, a Vertex Model Garden partner, Grok, Qwen, GLM,
   DeepSeek, Kimi, Gemma, or a self-hosted open model) by registering it + its provider, with
   **zero changes to task logic**.
2. **Run our real claim-processing tasks** (starting with audit + itemized bills; growing to
   segmentation, item categorisation/extraction, NME, benefit plan, policy) on real sample
   claim documents.
3. **Store everything** — prompt, structured input, raw + parsed output, response, time taken,
   and the full token breakdown (input / output / thinking / cached / batched) plus estimated
   cost in USD/INR — in Postgres for durable comparison and audit.
4. **Compare objectively** — accuracy, confidence, performance, and cost — via an **unbiased,
   truthful multi-signal scorer** (deterministic field metrics + neutral LLM-as-judge +
   cost/latency), surfacing the **cheapest model that clears an accuracy threshold** per task.
5. **Handle every model's caveats correctly** — input/output format differences, image vs PDF
   handling, size limits, structured-output method, thinking/caching/batching — through a
   capability + adapter layer so callers never special-case a model.

## Why we are building it (context)

- `superclaims-ai` and `healthpay-ai` (sibling folders) already run a mature claim-processing
  pipeline, but it is **hard-wired to Gemini on Vertex AI** (`langchain_google_genai`,
  `ChatGoogleGenerativeAI`, a Gemini-only `if/elif` in
  `superclaims-ai/backend/app/lang_graph/llm/client.py`). There is **no way to fairly compare
  other models** on our actual tasks, and **no systematic record** of cost/accuracy trade-offs.
- We want to drive **cost efficiency** without sacrificing accuracy — which requires running
  identical work across models and measuring it the same way.
- Models differ in real, breaking ways (e.g. Grok caps base64 images at 4 MB and needs PDFs as
  images; DeepSeek R1 is text-only; Vertex caps payloads at 30 MB; structured-output support
  varies). A naive "swap the client" approach silently fails. Colosseum makes the caveats
  explicit, tested, and handled.

## What we are starting with (v1 scope)

- **Tasks**: `audit` + `itemized_bills`, vendored from `superclaims-ai` with the **core task
  instructions and mandatory structured-output schemas preserved**, but the Gemini/Vertex-
  specific wording **de-tuned** so prompts are model-neutral.
- **Models**: Gemini on **Vertex AI** first, then **Vertex Model Garden** partners and external
  providers. Credentials reused from `superclaims-ai/.env` and `healthpay-ai/.env`; Langfuse
  keys to be provided.
- **Stack**: LiteLLM (transport + cost) + Instructor (structured output) + a custom
  capability/adapter layer, orchestrated with LangGraph; Postgres + SQLModel for storage;
  FastAPI + a lightweight Vite/React dashboard; Redis (minimal, for cache/dedup); Temporal
  deferred behind an asyncio runner; no RAG until a retrieval-dependent agent is ported.
- **Scoring**: multi-signal (field metrics + LLM-judge + cost/latency) → composite scoreboard.

## Stack decisions & rationale (summary)

| Area | Choice | Why |
|---|---|---|
| Transport | LiteLLM + Instructor + custom capability/adapter layer | 100+ providers in OpenAI format with built-in cost tracking; Instructor adds Pydantic validation + retries; our layer encodes per-model caveats so callers stay uniform |
| Orchestration | LangGraph per task; model binding via `ModelGateway` | Mirrors superclaims-ai, traceable in Langfuse, room to grow to multi-node agents — but the model call is provider-agnostic, not `ChatGoogleGenerativeAI` |
| Structured output | Instructor (not `.with_structured_output`) | Native structured-output reliability varies wildly across providers; Instructor normalizes + retries + validates |
| Storage | Postgres + SQLModel | Durable "store everything" record of runs, tokens, cost, outputs, scores |
| Batch orchestration | asyncio runner now, Temporal later | Right-sized: local dev stays simple; Temporal added for durable large fan-out when needed |
| Cache/queue | Redis, minimal | Response dedup + rate-limit coordination only |
| Retrieval | RAG deferred | Audit + bills don't need retrieval; add when policy/benefit agents are ported |
| Frontend | Vite/React dashboard | Side-by-side outputs + cost/accuracy leaderboard |
| Observability | Langfuse | Traces across LiteLLM + LangChain |

## Non-negotiables

- **Mandatory structured output** for every task (Pydantic schema, validated).
- **Unbiased, truthful scoring** — a model never judges its own output; judge order is
  randomized; deterministic metrics ground the subjective judge.
- **Caveats are explicit and tested** — document conversion/compression/merging and per-model
  size/format limits have golden tests; capability flags are verified live against provider
  docs, never assumed.
- **Docs and code stay in sync** — the in-code capability registry is generated to match
  [models-and-caveats.md](./models-and-caveats.md).

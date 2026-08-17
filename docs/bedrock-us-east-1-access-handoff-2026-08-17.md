# Bedrock `us-east-1` access handoff — 2026-08-17

## Purpose

Record the AWS Bedrock discovery and live-access checks performed for the
SuperClaims AWS account, and how to use the result safely in Colosseum. This
document deliberately contains **no credentials, bearer token, or account ID**.

## What was checked

1. The supplied IAM credentials authenticated successfully and could enumerate
   the Bedrock foundation-model catalog in `us-east-1`.
2. Small live `Converse` probes were made with `maxTokens=1` for the requested
   models. A successful probe is the only reliable confirmation of both IAM and
   account/model entitlement.
3. The AWS Billing `GetCredits` API was attempted, but the IAM principal lacks
   `billing:GetCredits`.
4. Colosseum's existing Bedrock catalog, gateway, environment contract, and
   verification scripts were inspected. No Colosseum code or catalog entry was
   changed by this investigation.

## Live results (this AWS account, `us-east-1`)

| Model / path | Result | Meaning |
|---|---|---|
| `qwen.qwen3-vl-235b-a22b` | **Success** — 12 input / 1 output token | Direct `Converse` is allowed. This is currently the only model confirmed callable with these credentials. |
| `anthropic.claude-sonnet-4-6` | Requires an inference profile | Bare model IDs do not have on-demand throughput. |
| `us.anthropic.claude-sonnet-4-6` | **Blocked** — `INVALID_PAYMENT_INSTRUMENT` | IAM reached the model, but AWS Marketplace cannot complete the Anthropic subscription until the AWS account has a valid payment instrument. |
| `anthropic.claude-opus-4-6-v1` | Requires an inference profile | Bare model IDs do not have on-demand throughput. |
| `us.anthropic.claude-opus-4-6-v1` | **Blocked** — `INVALID_PAYMENT_INSTRUMENT` | Same AWS Marketplace/payment blocker as Sonnet. |
| `openai.gpt-5.6-luna` | **Blocked** — `AccessDeniedException` / not available for this account | Listing in the catalog is not entitlement. AWS says this needs an additional access option/AWS Sales. |

The successful Qwen request consumed a tiny amount of Bedrock usage. Denied
requests generated no inference output.

## Relevant `us-east-1` catalog entries

`ListFoundationModels` shows a catalog, not a promise that the account can
invoke every entry. Re-run a one-token probe after changing model access,
payment, or region.

### Qwen

| Display name | Bedrock model ID |
|---|---|
| Qwen3-VL 235B A22B | `qwen.qwen3-vl-235b-a22b` |
| Qwen3 Coder Next | `qwen.qwen3-coder-next` |
| Qwen3 Next 80B A3B | `qwen.qwen3-next-80b-a3b` |
| Qwen3 32B | `qwen.qwen3-32b-v1:0` |
| Qwen3 Coder 30B A3B | `qwen.qwen3-coder-30b-a3b-v1:0` |

Important: the vision model ID has **no `-instruct` suffix**. The confirmed
call was text-only; Colosseum must separately probe rasterized-image input
before marking its vision path verified for this account.

### Anthropic

Catalog-listed Sonnet: 4, 4.5, 4.6, and 5. Catalog-listed Opus: 4.1, 4.5,
4.6, 4.7, 4.8, and 5. Current known profile IDs include:

```text
us.anthropic.claude-sonnet-4-6
global.anthropic.claude-sonnet-4-6
us.anthropic.claude-opus-4-6-v1
global.anthropic.claude-opus-4-6-v1
```

Do not enable any new Claude entry for this credential set until the AWS
payment/Marketplace blocker is fixed and a live structured-output probe passes.
Anthropic also requires its one-time use-case flow.

### DeepSeek

```text
deepseek.v3.2
deepseek.r1-v1:0
```

DeepSeek R1 is a reasoning/text model. It should remain gated out of
image/PDF comparison tasks unless an explicit vision-capable variant is used.

### Mistral

```text
mistral.mistral-large-3-675b-instruct
mistral.devstral-2-123b
mistral.ministral-3-14b-instruct
mistral.ministral-3-8b-instruct
mistral.ministral-3-3b-instruct
mistral.magistral-small-2509
mistral.mistral-7b-instruct-v0:2
mistral.mixtral-8x7b-instruct-v0:1
mistral.mistral-large-2402-v1:0
mistral.mistral-small-2402-v1:0
mistral.pixtral-large-2502-v1:0
mistral.voxtral-mini-3b-2507
mistral.voxtral-small-24b-2507
```

Treat Voxtral as audio/speech work, not a normal Colosseum text or rasterized
PDF benchmark, until an audio-input task exists.

### OpenAI and other open-weight options

```text
openai.gpt-5.6-luna       # listed, but explicitly unavailable to this account
openai.gpt-5.6-terra     # listed; not yet live-probed
openai.gpt-5.6-sol       # listed; not yet live-probed
openai.gpt-oss-20b-1:0   # listed; not yet live-probed
openai.gpt-oss-120b-1:0  # listed; not yet live-probed

meta.llama3-8b-instruct-v1:0
meta.llama3-70b-instruct-v1:0
meta.llama3-1-8b-instruct-v1:0
meta.llama3-1-70b-instruct-v1:0
meta.llama3-3-70b-instruct-v1:0
meta.llama4-scout-17b-instruct-v1:0
meta.llama4-maverick-17b-instruct-v1:0
```

Other catalog families (Nova, Cohere, Gemma, GLM, Kimi, MiniMax, Nemotron)
were also returned by the catalog. They have not been re-verified with this
credential set in `us-east-1` and must not be assumed callable.

## Credits and billing

No credit balance was obtained. AWS returned an authorization failure for
`billing:GetCredits`. An account administrator must grant that action (and
Billing-console access if using the UI), then read the Credits page or call
`aws billing get-credits`.

Eligible AWS promotional credits are applied automatically to eligible Bedrock
charges. They are not configured in the Bedrock request or Colosseum model
catalog. A valid payment instrument is still required for the blocked
Anthropic Marketplace subscription.

## Colosseum status and integration guidance

Colosseum already has the relevant plumbing:

- `backend/app/providers/catalog/bedrock.yaml` already contains
  `bedrock-qwen3-vl-235b` with the correct transport ID
  `bedrock/qwen.qwen3-vl-235b-a22b`.
- `backend/app/providers/gateway.py` uses LiteLLM's `bedrock/` transport.
- `scripts/verify_bedrock.py` does catalog listing plus a one-token smoke test.
- The existing contract is a short-lived `AWS_BEARER_TOKEN_BEDROCK` in
  `ap-south-1`. Its own documentation reports that the current bearer token
  was stale when last checked.

This investigation used direct AWS SDK credentials in **`us-east-1`**, not
the expired bearer-token path in **`ap-south-1`**. Do not mix the two results:
regions, inference profiles, entitlements, and Marketplace status can differ.

### Recommended next steps (do not apply automatically)

1. Rotate the IAM access key that was shared in conversation. Store replacement
   credentials only in the deployment secret manager, or preferably use an AWS
   workload role; never commit credentials or a bearer token.
2. Fix the AWS account's payment instrument and complete the Anthropic first-use
   flow. Then rerun a one-token check against the `us.` inference profiles.
3. Keep GPT-5.6 Luna disabled for this account until AWS enables it; do not add
   a retry workaround for an account-level `AccessDeniedException`.
4. Configure Colosseum for one region and one credential mechanism at a time.
   For this account, start with `us-east-1` and the already-confirmed
   `bedrock-qwen3-vl-235b` transport ID.
5. Run the existing verification command before changing any catalog flags:

   ```bash
   uv run python scripts/verify_bedrock.py --model bedrock-qwen3-vl-235b
   ```

6. Only after the Qwen vision probe and a structured-output Colosseum task pass,
   keep it enabled for document-image benchmarks. Otherwise, mark it text-only
   for the applicable task packs.

## Changes made elsewhere

Before this handoff request, a small, uncommitted Bedrock API was added to the
SuperClaims repository. It exposes superadmin-only model listing and bounded
text `Converse` calls. It is not required for Colosseum, which already has a
native LiteLLM Bedrock transport. No further SuperClaims changes were made
while preparing this document.

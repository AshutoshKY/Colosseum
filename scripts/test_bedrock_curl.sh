#!/usr/bin/env bash
# Smoke-test Bedrock models directly via the runtime Converse endpoint.
# Usage: ./scripts/test_bedrock_curl.sh   (reads AWS_BEARER_TOKEN_BEDROCK from .env)
set -euo pipefail
REGION="${AWS_REGION_NAME:-ap-south-1}"
TOKEN=$(grep '^AWS_BEARER_TOKEN_BEDROCK=' .env | sed 's/^AWS_BEARER_TOKEN_BEDROCK=//' | tr -d '"'"'"'')
RT="https://bedrock-runtime.${REGION}.amazonaws.com"

# transport ids exactly as Colosseum routes them (bare / apac. / global. prefixes)
MODELS=(
  "qwen.qwen3-vl-235b-a22b"                        # Qwen3-VL (the one you asked for)
  "qwen.qwen3-235b-a22b-2507-v1:0"                 # Qwen3 235B Instruct
  "qwen.qwen3-coder-480b-a35b-v1:0"                # Qwen3 Coder 480B
  "google.gemma-3-27b-it"                          # Gemma 3 27B (vision)
  "openai.gpt-oss-120b-1:0"                        # GPT-OSS 120B
  "mistral.mistral-large-3-675b-instruct"          # Mistral Large 3
  "deepseek.v3.2"                                  # DeepSeek V3.2
  "zai.glm-5"                                      # GLM-5
  "apac.amazon.nova-lite-v1:0"                     # Nova Lite (apac. profile)
  "global.amazon.nova-2-lite-v1:0"                 # Nova 2 Lite (global. profile)
  "global.anthropic.claude-opus-4-5-20251101-v1:0" # Claude Opus 4.5 (global. profile)
)
for M in "${MODELS[@]}"; do
  CODE=$(curl -s -o /tmp/br_out.json -w "%{http_code}" -X POST "$RT/model/$M/converse" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    --data '{"messages":[{"role":"user","content":[{"text":"Reply with the single word OK"}]}],"inferenceConfig":{"maxTokens":8}}')
  case "$CODE" in
    200) MSG=$(python3 -c "import json;print(json.load(open('/tmp/br_out.json'))['output']['message']['content'][0]['text'])" 2>/dev/null || echo ok);;
    *)   MSG=$(head -c 90 /tmp/br_out.json);;
  esac
  printf "HTTP %s  %-48s %s\n" "$CODE" "$M" "$MSG"
done

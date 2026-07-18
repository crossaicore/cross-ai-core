# Providers — cross-ai-core

`cross-ai-core` supports six AI providers through a single `process_prompt()` interface.
You only need API keys for the providers you actually use — **Ollama is keyless** (it runs
models locally or on your LAN).

## Quick-pick guide

| Provider key | Model family | Best for | Free tier |
|---|---|---|---|
| `"xai"` | Grok 4 | Current events, fast reasoning | ⚠️ Limited credits |
| `"anthropic"` | Claude 4 | Deep reasoning, high-quality prose | ❌ No |
| `"openai"` | GPT-4o | Reliable baseline, structured output | ❌ No |
| `"perplexity"` | Sonar Pro | Live web search with citations | ❌ No |
| `"gemini"` | Gemini 2.5 | Long context, getting started | ✅ Yes |
| `"ollama"` | Llama 3.1 & any local model | Private / offline, no API key, no billing | ✅ Free (self-hosted) |

---

## xAI — `"xai"`

**Default model:** `grok-4-1-fast-reasoning`  
**Key variable:** `XAI_API_KEY`  
**Get a key:** [console.x.ai](https://console.x.ai)  
**Install:** `pip install "cross-ai-core[xai]"`

xAI's Grok models use an **Anthropic-compatible API** at `https://api.x.ai`.
`cross-ai-core` uses the Anthropic SDK with a custom `base_url` — no separate SDK required.

**Strengths:**
- Fast reasoning with `grok-4-1-fast-reasoning`; strong on current events and technology
- More opinionated and direct than most models — makes clear, verifiable claims
- Trained on X / Twitter data; good awareness of named individuals and recent discourse

**Notes:** Free credits for new accounts deplete quickly. Set a spending limit in the xAI console.

---

## Anthropic — `"anthropic"`

**Default model:** `claude-opus-4-5`  
**Key variable:** `ANTHROPIC_API_KEY`  
**Get a key:** [console.anthropic.com](https://console.anthropic.com) — credit card required  
**Install:** `pip install "cross-ai-core[anthropic]"`

Claude is built around long, structured, carefully hedged responses.
`cross-ai-core` enables **extended thinking** (`budget_tokens: 10000`) by default on
Claude 3.7+ and Claude 4 models — the model reasons internally before replying.

**Strengths:**
- Highest-quality prose and document structure
- Extended thinking mode for deep multi-step reasoning
- Low tendency toward confident false statements

**Notes:** `claude-opus-4-5` is the most capable but also the most expensive per token.
Use `claude-sonnet-4-5` for a faster, cheaper alternative.

---

## OpenAI — `"openai"`

**Default model:** `gpt-4o`  
**Key variable:** `OPENAI_API_KEY`  
**Get a key:** [platform.openai.com](https://platform.openai.com) — credit card required  
**Install:** `pip install "cross-ai-core[openai]"`

GPT-4o is a reliable, well-rounded model with a 128K token context window.
Consistent output format makes it a solid baseline.

**Strengths:**
- Stable, predictable output; reliable for downstream parsing pipelines
- Strong across a wide range of general-knowledge domains
- 128K context handles large payloads without truncation

**Notes:** OpenAI's free tier has been removed — a small prepaid credit is required.
API latency can be higher than Gemini or xAI under load.

---

## Perplexity — `"perplexity"`

**Default model:** `sonar-pro`  
**Key variable:** `PERPLEXITY_API_KEY`  
**Get a key:** [perplexity.ai/settings/api](https://www.perplexity.ai/settings/api) — paid plan or API credits  
**Install:** `pip install cross-ai-core` *(no extra SDK — uses `requests`)*

Perplexity's Sonar models do **live web search with citations** before generating a response.
This makes them uniquely suited to current-events questions where training cut-offs matter.

**Strengths:**
- Grounded responses — citations reduce hallucination on time-sensitive facts
- Naturally produces claim-level structure with source URLs
- No extra SDK dependency — pure HTTP via `requests`

**Notes:** Response times are higher than other providers because each call includes a search step.

---

## Google Gemini — `"gemini"`

**Default model:** `gemini-2.5-flash`  
**Key variable:** `GEMINI_API_KEY`  
**Get a key:** [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) — **free, no credit card**  
**Install:** `pip install "cross-ai-core[gemini]"`

Gemini is the recommended starting point for new users: genuinely free tier,
fast responses, and a massive 1M-token context window.

**Free tier limits:** 15 req/min · 1,500 req/day · 1M tokens/day

**Strengths:**
- Only provider with a free API tier — ideal for development and exploration
- 1M token context window; handles very large prompts without truncation
- Reliable structured output; low hallucination rate on factual domains

**Notes:** Gemini occasionally produces safety refusals on politically sensitive topics.
If a prompt triggers one, rephrase or use a different provider.

---

## Ollama — `"ollama"` (local / LAN, keyless)

**Default model:** `llama3.1`  
**Config variable:** `OLLAMA_BASE_URL` (default `http://localhost:11434`)  
**Get started:** [ollama.com/download](https://ollama.com/download) — then `ollama pull llama3.1`  
**Install:** `pip install cross-ai-core` *(no extra SDK — uses `requests`)*

Ollama is the first **local** and first **keyless** provider. It talks to an Ollama
daemon over HTTP (`POST /api/generate`, non-streaming) instead of a cloud API — so
there is **no API key** and, on a trusted network, **your prompts never leave your
hardware**. `check_api_key("ollama")` always returns `True`, and `ollama` is
deliberately absent from `keys.PROVIDER_API_KEY_ENV`; any consumer that filters by
`has_api_key()` must treat it as always-available.

**Strengths:**
- Fully private / offline — nothing is sent to a third-party provider
- No API key and no per-token billing — run open-weight models for free
- Point `OLLAMA_BASE_URL` at a beefier LAN host to offload generation

**Config variables:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Daemon location — local or a LAN host |
| `OLLAMA_MODEL` | `llama3.1` | Default model (resolved via the generic `<MAKE>_MODEL` path) |
| `OLLAMA_API_TOKEN` | *(empty)* | Optional `Authorization: Bearer` token for reverse-proxied daemons |
| `OLLAMA_REQUEST_TIMEOUT` | `120` | Generation request timeout, seconds |
| `OLLAMA_HEALTH_CHECK_TIMEOUT` | `5` | Connectivity/discovery probe timeout, seconds |
| `OLLAMA_MAX_CONCURRENCY` | `2` | Hardware-bound concurrency cap (host RAM/VRAM, not network) |

**Connectivity helpers:** `OllamaHandler.health_check()` (never raises),
`require_healthy()` (raises `ConnectionError` with a hint if down), and
`list_models()` (installed model tags; `[]` on failure).

**Notes:** Concurrency is bound by host RAM/VRAM, not network — the cap defaults to
2 (override with `OLLAMA_MAX_CONCURRENCY`). A daemon can be up with zero models
pulled; run `ollama pull <model>` first.

---

## Using multiple providers in parallel

All six providers can run simultaneously — since `process_prompt` is I/O-bound,
Python threads give true parallelism:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from cross_ai_core import process_prompt, get_content, get_ai_list

prompt = "What will be the biggest AI story this week?"
system = "You are a concise technology journalist."

def call_one(provider):
    result = process_prompt(provider, prompt, system=system, use_cache=True)
    return provider, get_content(provider, result.response)

with ThreadPoolExecutor(max_workers=5) as pool:
    futures = {pool.submit(call_one, p): p for p in get_ai_list()}
    for future in as_completed(futures):
        try:
            provider, text = future.result()
            print(f"\n=== {provider} ===\n{text[:400]}\n")
        except Exception as e:
            print(f"  {futures[future]} failed: {e}")
```

See the [API reference](api-reference.md#parallel-calls) for a two-provider example and error handling patterns.

---

## Environment variable summary

| Variable | Provider |
|----------|----------|
| `XAI_API_KEY` | xAI / Grok |
| `ANTHROPIC_API_KEY` | Anthropic / Claude |
| `OPENAI_API_KEY` | OpenAI |
| `PERPLEXITY_API_KEY` | Perplexity |
| `GEMINI_API_KEY` | Google Gemini |
| `OLLAMA_BASE_URL` | Ollama daemon location (keyless — local/LAN, default `http://localhost:11434`) |
| `OLLAMA_MODEL` | Ollama default model (default `llama3.1`) |
| `DEFAULT_AGENT` | Which agent `get_default_ai()` returns (set by `st-admin > AI > d`) |
| `DEFAULT_AI` | Legacy pre-Agents-v2 spelling of `DEFAULT_AGENT`; still read for back-compat |
| `CROSS_AI_AGENTS_FILE` | Override default `~/.cross_ai_models.json` agent registry path |
| `CROSS_API_CACHE_DIR` | Override default `~/.cross_api_cache/` directory |
| `CROSS_NO_CACHE` | Set to `1` to disable caching globally |

The library **never calls `load_dotenv()`**. Load your `.env` or `~/.crossenv`
in your application before importing `cross_ai_core`.

---

**Next:** [API reference](api-reference.md)


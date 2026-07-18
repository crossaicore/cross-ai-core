# API Reference — cross-ai-core

The entire public API is importable directly from `cross_ai_core`.  
You never need to import individual provider modules (`ai_xai.py`, `ai_anthropic.py`, etc.) —
that is the point: swap providers without changing any other code.

```python
from cross_ai_core import (
    process_prompt, get_content, get_usage,
    get_default_ai, get_ai_list, check_api_key,
    AIResponse, RateLimitError, QuotaExceededError,
)
```

---

## Core dispatch

### `process_prompt`

```python
def process_prompt(
    ai_key: str,
    prompt: str,
    *,
    system: str | None = None,
    verbose: bool = False,
    use_cache: bool = True,
) -> AIResponse
```

Sends `prompt` to the provider identified by `ai_key` and returns an `AIResponse`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ai_key` | `str` | — | Provider key: `"xai"`, `"anthropic"`, `"openai"`, `"perplexity"`, `"gemini"`, or `"ollama"` (or any configured agent name) |
| `prompt` | `str` | — | The user message to send |
| `system` | `str \| None` | `None` | System / persona prompt. `None` uses the provider's built-in default |
| `verbose` | `bool` | `False` | Print cache-hit / miss messages to stdout |
| `use_cache` | `bool` | `True` | Cache response by MD5 of the request payload |

**Returns** an `AIResponse` (see below).  
**Raises** `ValueError` for an unknown `ai_key`; re-raises provider SDK exceptions after
classifying and printing a user-friendly error via `handle_api_error`.

```python
result = process_prompt("gemini", "What is a transformer?",
                        system="You are a concise technical writer.",
                        use_cache=True)
```

---

### `AIResponse`

The object returned by `process_prompt`.

| Attribute | Type | Description |
|-----------|------|-------------|
| `.payload` | `dict` | The request payload sent to the API |
| `.client` | object | The provider SDK client that was used |
| `.response` | `dict` | The raw JSON response from the API |
| `.model` | `str` | Model string that was used (e.g. `"grok-4-1-fast-reasoning"`) |
| `.was_cached` | `bool` | `True` if the response came from the local MD5 cache |

`AIResponse` also unpacks as a 4-tuple `(payload, client, response, model)` for
backward compatibility with older call-sites.

```python
result = process_prompt("openai", prompt)
print(result.model)          # "gpt-4o"
print(result.was_cached)     # True / False

# Backward-compatible unpacking still works:
payload, client, response, model = process_prompt("openai", prompt)
```

---

### `get_content`

```python
def get_content(ai_key: str, response: dict) -> str
```

Extracts the plain-text reply from a raw API `response` dict.  
Each provider returns text in a different location inside the response; this
function hides that difference.

```python
text = get_content("anthropic", result.response)
print(text)
```

---

### `put_content`

```python
def put_content(ai_key: str, report: str, response: dict) -> dict
```

Writes a new text string back into the `response` dict, in the correct
provider-specific field.  Useful when you post-process the text and need
to store the edited version in the same structure.

```python
edited = result.response.copy()
edited = put_content("xai", cleaned_text, edited)
```

---

### `get_data_content`

```python
def get_data_content(ai_key: str, select_data: dict) -> str
```

Like `get_content`, but operates on a *data container* dict (a dict that has
`"gen_response"` as a nested key).  Used when the response has been wrapped
in a larger storage structure.

---

### `get_data_title`

```python
def get_data_title(ai_key: str, data: dict) -> str
```

Returns the first line of the content in `data` — treated as the title.

---

### `get_usage`

```python
def get_usage(ai_key: str, response: dict) -> dict
```

Extracts token counts from a raw API response dict, normalised across all providers.

```python
usage = get_usage("anthropic", result.response)
# {"input_tokens": 512, "output_tokens": 1024, "total_tokens": 1536}
```

Returns `{"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}` if the
provider or field is absent.

---

## Provider helpers

### `get_default_ai`

```python
def get_default_ai() -> str | None
```

Returns the user-configured default agent name.

Resolution order (post-AGT-1, cross-ai-core 0.8.0+):
1. `DEFAULT_AGENT` environment variable — if set and present in the agent registry
2. `DEFAULT_AI` environment variable — legacy back-compat for the same purpose
3. First entry in the agent registry (`~/.cross_ai_models.json`)
4. `None` if no agents are defined

```python
agent = get_default_ai()      # DEFAULT_AGENT, then DEFAULT_AI, then first agent
if agent is None:
    raise SystemExit("No agents defined — run 'st-admin --setup' or write ~/.cross_ai_models.json by hand")
result = process_prompt(agent, prompt)
```

> The pre-0.8.0 fallback to a hardcoded `"xai"` was removed when auto-seeding of built-in makes ended.  Callers that need a guaranteed default should seed the registry up front.

---

### `get_ai_list`

```python
def get_ai_list() -> list[str]
```

Returns `["xai", "anthropic", "openai", "perplexity", "gemini", "ollama"]` — the full list
of registered provider keys.  Use this to iterate over all providers without
hardcoding names.

---

### `get_ai_model`

```python
def get_ai_model(ai_key: str) -> str
```

Returns the model string compiled into the provider module, e.g. `"claude-opus-4-5"`.

---

### `get_ai_make`

```python
def get_ai_make(ai_key: str) -> str
```

Returns the provider's make string (same as `ai_key` for most providers).

---

### `check_api_key`

```python
def check_api_key(ai_make: str, paths_checked: list | None = None) -> bool
```

Verifies that the required API key is present in `os.environ`.  
If the key is missing, prints a clear diagnostic listing the `.env` files
that were searched and the exact variable name to add.

```python
if not check_api_key("gemini"):
    sys.exit(1)     # key missing; diagnostic already printed
```

---

## Parallel calls

Because `process_prompt` is I/O-bound (network), you can call multiple providers
simultaneously with `ThreadPoolExecutor`:

### Two providers

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from cross_ai_core import process_prompt, get_content

prompt = "Explain quantum entanglement in two sentences."
system = "You are a concise science communicator."

def call_one(provider):
    result = process_prompt(provider, prompt, system=system)
    return provider, get_content(provider, result.response)

with ThreadPoolExecutor(max_workers=2) as pool:
    futures = {pool.submit(call_one, p): p for p in ["xai", "anthropic"]}
    for future in as_completed(futures):
        provider, text = future.result()
        print(f"\n=== {provider} ===\n{text}\n")
```

### All six providers

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from cross_ai_core import process_prompt, get_content, get_ai_list

prompt = "What are the risks of AGI?"
system = "You are a concise technical writer."

def call_one(provider):
    result = process_prompt(provider, prompt, system=system, use_cache=True)
    return provider, get_content(provider, result.response)

providers = get_ai_list()   # ["xai", "anthropic", "openai", "perplexity", "gemini", "ollama"]

with ThreadPoolExecutor(max_workers=len(providers)) as pool:
    futures = {pool.submit(call_one, p): p for p in providers}
    results = {}
    for future in as_completed(futures):
        provider, text = future.result()
        results[provider] = text
        print(f"✓ {provider} done")

# results is now a dict keyed by provider
for provider in providers:          # re-order to deterministic sequence
    print(f"\n=== {provider} ===\n{results[provider][:400]}\n")
```

> **Note:** `process_prompt` classifies and prints errors itself on failure.
> Wrap `future.result()` in a try/except if you want to continue when one
> provider fails rather than raising:
>
> ```python
> try:
>     provider, text = future.result()
> except Exception as e:
>     print(f"  {futures[future]} failed: {e}")
>     continue
> ```

---

## Caching

Responses are cached by MD5 hash of the full request payload in `~/.cross_api_cache/`.  
The same prompt + model + system + parameters always resolves to the same hash,
so repeated calls return instantly from disk.

```python
# Bypass cache for one call
result = process_prompt(provider, prompt, use_cache=False)

# Check if a response came from cache
if result.was_cached:
    print("served from cache")

# Find / override the cache directory
from cross_ai_core import get_cache_dir
print(get_cache_dir())   # reads CROSS_API_CACHE_DIR, defaults to ~/.cross_api_cache/
```

The cache is safe to delete at any time — the library recreates it on the next call.

---

## Error handling

### How errors flow out of `process_prompt`

When a provider call fails, `process_prompt` passes the exception to
`handle_api_error`, which classifies it and raises a typed exception:

| Exception | Meaning | `process_prompt` behaviour |
|-----------|---------|--------------------------|
| `QuotaExceededError` | Billing limit / credits exhausted | Prints a dashboard URL, then **calls `sys.exit(1)`** |
| `RateLimitError` | Too many requests (429, transient) | Raises — caller decides whether to retry |
| `TransientError` | Service unavailable (500, 503, overload) | Raises — caller decides whether to retry |
| `CrossAIError` | Base class for all of the above | — |

### The `sys.exit` issue — and how to work around it

`QuotaExceededError` by default calls `sys.exit(1)`. This is intentional for CLI
tools — a clear message and immediate stop — but it is hostile to library use:
any code that runs `process_prompt` inside a thread, a background task, or a
try/except will be **killed silently**.

The simplest defence is to wrap `process_prompt` in a function that converts
`SystemExit` into a regular exception your application can handle:

```python
from cross_ai_core import process_prompt, QuotaExceededError

def safe_prompt(provider, prompt, **kwargs):
    """Wrap process_prompt so sys.exit() becomes a catchable exception."""
    try:
        return process_prompt(provider, prompt, **kwargs)
    except SystemExit:
        raise QuotaExceededError(f"Quota exceeded for {provider}", ai_name=provider)
```

You can then catch it normally:

```python
try:
    result = safe_prompt("openai", prompt)
except QuotaExceededError as e:
    print(f"Out of credits for {e.ai_name} — switching provider")
    result = safe_prompt("gemini", prompt)   # fallback
```

### Parallel calls with per-provider fallback

When running all six providers in parallel, you usually want one provider's
failure to not cancel the others.  Use the `safe_prompt` wrapper with a
try/except inside the thread:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from cross_ai_core import process_prompt, get_content, get_ai_list, QuotaExceededError

def safe_prompt(provider, prompt, **kwargs):
    try:
        return process_prompt(provider, prompt, **kwargs)
    except SystemExit:
        raise QuotaExceededError(f"Quota exceeded for {provider}", ai_name=provider)

def call_one(provider, prompt):
    result = safe_prompt(provider, prompt, use_cache=True)
    return provider, get_content(provider, result.response)

prompt = "What is the current state of AI safety research?"

with ThreadPoolExecutor(max_workers=5) as pool:
    futures = {pool.submit(call_one, p, prompt): p for p in get_ai_list()}
    results = {}
    for future in as_completed(futures):
        provider = futures[future]
        try:
            _, text = future.result()
            results[provider] = text
        except QuotaExceededError as e:
            print(f"  {e.ai_name}: quota exceeded — add credits at the provider dashboard")
        except Exception as e:
            print(f"  {provider}: {e}")
```

### Retry with backoff

For rate limits and transient errors, use `retry_with_backoff`:

```python
from cross_ai_core import retry_with_backoff, process_prompt

result = retry_with_backoff(
    lambda: process_prompt("openai", prompt),
    ai_name="openai",
    max_retries=3,
    wait_seconds=15,   # doubles on each retry: 15s → 30s → 60s
)
```

`retry_with_backoff` handles `RateLimitError` and `TransientError` automatically.
It will still call `sys.exit(1)` on `QuotaExceededError` (permanent — no point
retrying). Apply the `safe_prompt` wrapper around `retry_with_backoff` if you
need to catch that too.

---

## Registry

`AI_HANDLER_REGISTRY` maps provider keys to handler classes.  In tests, patch
it with a mock to avoid real API calls:

```python
from unittest.mock import patch
from cross_ai_core import AI_HANDLER_REGISTRY

with patch.dict(AI_HANDLER_REGISTRY, {"xai": MockXAIHandler}):
    result = process_prompt("xai", "test prompt")
```

---

**Next:** [Providers guide](providers.md)


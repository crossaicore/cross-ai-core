# Optional live usage smoke check

This check makes one small request through a selected provider's real handler
and SDK, extracts the text and usage, and prints a JSON result containing both
native metadata and normalized counts. It is separate from pytest and CI.

## Run it

Use this repository's virtual environment with the development extras and the
relevant provider SDK installed. Pass `--env-file ~/.crossenv` to read credentials
directly from that file:

```bash
cd ~/github/cross-ai-core
.venv/bin/python -m pip install -e ".[dev,openai]"

# Inspect the selected model and credential availability; no provider call.
.venv/bin/python -m tools.live_usage_smoke openai --model gpt-4o --env-file ~/.crossenv

# Opt in to one potentially billable request.
.venv/bin/python -m tools.live_usage_smoke openai --model gpt-4o --env-file ~/.crossenv --live
```

File loading uses `python-dotenv`, a development dependency. It reads the
explicitly selected file before importing the library, supports dotenv quoting
and comments, and preserves existing exported variables. It does not execute
shell commands or print keys. Without `--env-file`, only the process environment
is used. The production library continues to read environment variables only.

The positional argument accepts a configured agent name or a registered provider
make. It uses existing model resolution; `--model MODEL_ID` overrides the model
for this check. No model selection is saved. Other options are `--max-tokens`
(default 128) and `--timeout` (default 30 seconds).

Run each desired provider explicitly. A missing key, rejected request, timeout,
empty response or invalid usage is a failed check, not a silent skip or retry.
The command exits with status 1 on failure and 0 on success or dry run. Save the
JSON output by redirecting it to a local file if needed.

## What it verifies

- A fresh request reaches the existing handler and SDK path, bypassing the local
  response cache. The fixed prompt asks for `OK` without explanation or search.
- Text extraction returns the expected answer.
- Usage is complete, contains positive aggregate counts, and has no validation
  issues beyond an informational derived total.
- Native metadata is retained alongside the normalized usage report, allowing
  direct inspection of the provider's actual fields and returned model.

Limits and transport settings are temporary overrides inside this standalone
test process. The check disables SDK retries and the existing Anthropic extended
thinking budget; Ollama receives `num_predict`, and Gemini receives per-request
timeout/retry options. It does not change production handler defaults or cache
files. Its own offline tests verify these behaviors.

The output cap bounds the requested generated tokens, not the dollar invoice.
Provider search fees and model-specific reasoning behavior can differ. A model
may exhaust a small cap before producing visible text; the check records that
failure without increasing the limit or trying another model automatically.

## Scope

A pass validates this small request for this account, endpoint and model at the
time it ran. It does not prove provider-cache hits, every reasoning category,
long report behavior, invoice accuracy or future service availability. Those
would require additional, explicitly selected scenarios. Dispatcher and local
cache behavior remain covered by the offline suite.

Returned metadata is recorded even if later text extraction fails. An API error
records a redacted diagnostic and whether a response was received. No request
headers or credentials are included. Because the prompt is fixed and synthetic,
the emitted response contains no report data supplied by the caller.

SDK retry/timeout configuration follows the
[official OpenAI SDK documentation](https://developers.openai.com/api/reference/python)
and the installed Anthropic and Google SDK interfaces.

## November 5, 2026 results

One request per configured cloud provider, using the handler's existing model
default and a 128-token output cap. No retries or fallback models were used.

| Provider | Requested model | Result | Input / output / total |
|---|---|---|---|
| OpenAI | `gpt-4o` | Passed | 29 / 1 / 30 |
| Anthropic | `claude-opus-4-5` | Passed | 26 / 4 / 30 |
| xAI | `grok-4-1-fast-reasoning` | Passed | 213 / 86 / 299 |
| Perplexity | `sonar-pro` | Passed | 19 / 1 / 20 |
| Gemini | `gemini-2.5-flash` | Billing rejection: prepaid credits depleted | No generation usage returned |

xAI returned model `grok-4.3` for the requested identifier and reported 85 ordinary
input tokens plus 128 cache-read tokens. Normalization correctly included both
in the 213 aggregate input tokens. All four successful responses contained `OK`.
Perplexity reported a native total cost of $0.00388; other successful responses
did not include a dollar charge. No combined dollar-cost claim is made.

The [recorded JSON results](../tests/fixtures/live_usage_smoke_20261105.json) contain
timestamps, SDK versions, native metadata and normalized counts. The successful
samples now replay in the offline regression suite. Gemini remains unverified
live until its account has credits. Ollama was not selected for this initial run;
the later local-server checks are recorded below.

## Follow-up checks with explicit credential-file loading

The owner confirmed OpenAI passes using `--env-file ~/.crossenv`. Fresh CLI
checks then passed for Anthropic (26 input / 4 output), xAI (213 / 78), and
Perplexity (19 / 1). Native counters were checked directly against the normalized
counts. Gemini again returned HTTP 402 for depleted prepaid credits. Each check
used one request, the 128-token cap, and no retries.

The owner identified Ollama on flik and possibly m2mac. Both `flik.local` and
`m2mac.local` failed hostname resolution from the development Mac in Python,
macOS ping, and Bonjour lookup. Checking Ollama's standard port on 17 already
cached LAN neighbors found no responding service. No Ollama inference request
was made during that discovery attempt, and no network or service settings were
changed. The owner subsequently identified localhost-only services; the SSH
forwards below resolved access.

[Recorded follow-up results](test-results/usage-smoke-recheck-20261105.json).

## Local servers through SSH forwarding

flik (`172.16.0.9`) runs LM Studio on server-local port 1234. m2mac (`172.16.0.8`)
runs Ollama on server-local port 11434. Their SSH aliases provide host addresses
and identity keys, so the aliases work even when ordinary `.local` DNS lookup
does not. Keep each tunnel running in its own terminal:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:1235:127.0.0.1:1234 matt@flik.local
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:11435:127.0.0.1:11434 matt@m2mac.local
```

Check the native Ollama handler against m2mac:

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11435 .venv/bin/python -m tools.live_usage_smoke ollama --model llama3.1:latest --live
```

Check flik through the existing OpenAI-compatible handler. The dummy key satisfies
the SDK; this command connects to the local SSH forward and needs no cloud key:

```bash
OPENAI_BASE_URL=http://127.0.0.1:1235/v1 OPENAI_API_KEY=lm-studio .venv/bin/python -m tools.live_usage_smoke openai --model qwen/qwen3.5-35b-a3b --max-tokens 512 --live
```

The `provider: openai` field identifies the adapter in this LM Studio test, not
the inference host. The result artifact separately identifies the server and
base URL. Both products document their compatibility interfaces:
[LM Studio](https://lmstudio.ai/docs/developer/openai-compat) and
[Ollama](https://docs.ollama.com/api/openai-compatibility). The Ollama test above
uses its native `/api/generate` endpoint.

| Server/model | Output limit | Result | Input / output / total | Reasoning subset |
|---|---:|---|---|---:|
| m2mac, `llama3.1:latest` | 128 | Passed; `OK` | 34 / 2 / 36 | Not reported |
| flik, `qwen/qwen3.5-35b-a3b` | 128 | Usage valid; final text empty | 34 / 128 / 162 | 128 |
| flik, same model | 512 | Passed; `OK` | 34 / 178 / 212 | 174 |

The first Qwen check exhausted the cap on reasoning. One explicit follow-up with
a 512-token cap produced final text and confirmed reasoning is counted inside
output, not added again. There was no automatic retry or persistent model/server
configuration change. The [recorded local results](../tests/fixtures/local_usage_smoke_20261105.json)
include all three responses; their metadata now replays in the offline tests.

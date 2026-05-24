# cross-ai-core

[![PyPI version](https://img.shields.io/pypi/v/cross-ai-core.svg)](https://pypi.org/project/cross-ai-core/)
[![Python](https://img.shields.io/pypi/pyversions/cross-ai-core)](https://pypi.org/project/cross-ai-core/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Multi-provider AI dispatcher with MD5-keyed response caching and unified error handling.

Supports **Anthropic**, **xAI (Grok)**, **OpenAI**, **Google Gemini**, and **Perplexity** through a single consistent interface.

## Requirements

- **Python 3.10 or newer** (3.11 recommended for development)
- No upper version limit — tested on 3.10–3.13

## Install

Install only the provider(s) you need:

```bash
pip install "cross-ai-core[anthropic]"   # Claude
pip install "cross-ai-core[gemini]"      # Google Gemini
pip install "cross-ai-core[openai]"      # OpenAI (ChatGPT)
pip install "cross-ai-core[xai]"         # xAI Grok  (uses the OpenAI SDK)
pip install cross-ai-core                # Perplexity only (uses requests, no extra SDK)
```

Install all providers at once (used by [cross-st](https://github.com/crossaicore/cross-st), which runs all 5 simultaneously):

```bash
pip install "cross-ai-core[all]"
```

## Dependencies

`requests` is always installed — it is used for the Perplexity provider and general HTTP.  
The three provider SDKs are optional extras; pip installs only what you request.

| Extra | Package | Version | Providers covered |
|-------|---------|---------|-------------------|
| *(base)* | `requests` | ≥2.32.4 | Perplexity |
| `[anthropic]` | `anthropic` | ≥0.84.0 | Anthropic / Claude |
| `[gemini]` | `google-genai` | ≥1.65.0 | Google Gemini |
| `[openai]` | `openai` | ≥1.70.0 | OpenAI |
| `[xai]` | `openai` | ≥1.70.0 | xAI / Grok (OpenAI-compatible API) |
| `[all]` | all three above | — | All 5 providers |

## Quick start

Calls are dispatched through **agents** — named `(provider, model)` pairs.  See the [cross-st Agents wiki page](https://github.com/crossaicore/cross-st/wiki/Agents) for the full concept; the minimal version is one JSON file at `~/.cross_ai_models.json`:

```json
{
  "version": 2,
  "agents": {
    "xai":       {"make": "xai",       "model": null},
    "anthropic": {"make": "anthropic", "model": null}
  }
}
```

If you also use [`cross-st`](https://github.com/crossaicore/cross-st), running `st-admin --setup` once will detect every API key in `~/.crossenv` and seed one starter agent per provider for you.  Standalone users can write the file by hand or set `CROSS_AI_AGENTS_FILE=/path/to/file.json` to point at an alternative.

```python
import os
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.crossenv"))  # your app loads keys; the library reads os.environ

from cross_ai_core import process_prompt, get_content_auto, get_default_ai

agent  = get_default_ai()           # DEFAULT_AGENT env var, then DEFAULT_AI (legacy),
                                    # then first agent in ~/.cross_ai_models.json
result = process_prompt(
    agent,
    "Explain transformer attention in 3 sentences.",
    system="You are a concise technical writer.",   # omit to use each provider's default
    verbose=False,
    use_cache=True,
)
print(get_content_auto(result.response))            # auto-dispatches via the _make stamp
```

> **Breaking change in 0.8.0:** built-in provider names are no longer auto-registered as self-agents.  `process_prompt("xai", …)` raises `ValueError: Unsupported AI model: 'xai'. No agents defined.` if the registry is empty.  Define at least one agent (above) before the first call.

For older callers, `get_content(agent, result.response)` still works (it alias-resolves the agent → provider make internally).

## Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEFAULT_AGENT` | *(first agent in registry)* | Default agent when none is specified (set by `st-admin > AI > d` in cross-st 0.10+) |
| `DEFAULT_AI` | — | Legacy pre-Agents-v2 spelling of `DEFAULT_AGENT`; still read for back-compat |
| `CROSS_AI_AGENTS_FILE` | `~/.cross_ai_models.json` | Path to the agent registry JSON |
| `<AGENT_UPPER>_MODEL` | — | Per-agent model override (e.g. `ANTHROPIC_OPUS_MODEL=claude-opus-future`) |
| `<MAKE_UPPER>_MODEL` | — | Per-provider model override (e.g. `ANTHROPIC_MODEL=claude-3-5-haiku-latest`) |
| `XAI_API_KEY` | — | xAI / Grok API key |
| `ANTHROPIC_API_KEY` | — | Anthropic / Claude API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `PERPLEXITY_API_KEY` | — | Perplexity API key |
| `CROSS_API_CACHE_DIR` | `~/.cross_api_cache/` | Response cache directory |
| `CROSS_NO_CACHE` | — | Set to `1` to disable caching globally |
| `CROSS_NO_CLIENT_CACHE` | — | Set to `1` to disable per-provider client singleton caching |

The library only reads from `os.environ` — it never calls `load_dotenv()` itself.  
Load your `.env` or `~/.crossenv` before importing.  
You only need to set API keys for the providers you actually use.

## Caching

Responses are cached by MD5 hash of the request payload in `~/.cross_api_cache/`.  
The cache is safe to delete at any time.

```python
# Bypass cache for one call
result = process_prompt(provider, prompt, verbose=False, use_cache=False)

# Check if a response was served from cache
if result.was_cached:
    print("from cache")
```

## Development

```bash
cd ~/github/cross-ai-core
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"     # installs the package + pytest + pytest-mock
```

Run the test suite:

```bash
python -m pytest tests/ -v
```

Tests use mocks — no real API keys required.

> **Note:** Keep each repo's `.venv` separate; do not share it with dependent projects.

## Adding a provider

1. Create `cross_ai_core/ai_<name>.py` implementing `BaseAIHandler`
   (`get_payload`, `get_client`, `get_cached_response`, `get_model`, `get_make`,
   `get_content`, `put_content`, `get_data_content`, `get_title`, `get_usage`).
2. Register in `cross_ai_core/ai_handler.py`: add to `AI_HANDLER_REGISTRY` and `AI_LIST`.

## Documentation

- [API reference](docs/api-reference.md) — all public functions, `AIResponse`, parallel calls, error handling
- [Providers](docs/providers.md) — per-provider guide: models, API keys, strengths, free tiers
- [Changelog](CHANGELOG.md)

## Used by

| Project | PyPI | Description |
|---------|------|-------------|
| **cross-st** | [`cross-st`](https://pypi.org/project/cross-st/) | Multi-AI research reports with cross-product fact-checking. Installs this package automatically via `cross-ai-core[all]`. Full CLI toolkit — `pipx install cross-st`. |

> Building something with `cross-ai-core`? Open a PR or issue to get listed here.

## Community & support

Questions, ideas, bug reports, or just want to share what you're building?

- 💬 **[crossai.dev community forum](https://crossai.dev/)** — Discourse-powered discussion for `cross-ai-core`, `cross-st`, and the wider Cross family. Ask questions, share prompts, or compare provider results. Invite-only sign-up keeps it friction-free for real users; see the `cross-st` wiki for the one-command onboarding (`st-admin --discourse-setup`).
- 🐛 **[GitHub issues](https://github.com/crossaicore/cross-ai-core/issues)** — bug reports and feature requests.
- 🎬 **[YouTube @crossaicore](https://www.youtube.com/@crossaicore)** — walkthroughs and release notes.

Tagline: *AI reports. Cross-examined.*

## License

MIT — free for personal, academic, and open-source use.  
See [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md) for organizational and commercial use.

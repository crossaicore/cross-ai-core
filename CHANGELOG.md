# Changelog

All notable changes to `cross-ai-core` are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.11.0] — 2026-07-18  *(AGT-9 shim removal)*

Cleanup-only release. Completes the AGT-9 alias → agent rename by removing the
one-release deprecation **module** shim that was carried through 0.9.0 and
0.10.0. No change to the agent *API surface*; the canonical
`cross_ai_core.agents` module is unaffected. Also carries one **fix** (below)
for a keyless-provider dispatch crash found while dogfooding the 0.10.0 Ollama
provider.

### Removed
- **`cross_ai_core.aliases` module shim** (deprecated since 0.9.0). Import it and
  you now get `ModuleNotFoundError`. Migrate to `cross_ai_core.agents` — e.g.
  `from cross_ai_core.agents import resolve_agent` — or import the public names
  directly from the top-level `cross_ai_core` package.

### Fixed
- **Keyless-provider auto-dispatch crash** (`get_content_auto()` and the
  `get_content` / `put_content` / `get_data_title` / `get_data_content` /
  `get_usage` helpers). These resolved their `ai_key` argument strictly as an
  **agent name**, but `get_content_auto()` feeds them the raw stamped `_make`.
  Cloud providers worked by luck (agent name == make); for **keyless makes whose
  agent name differs from the make** — every Ollama agent, e.g. `ollama-qwen`
  with make `ollama` — `resolve_agent("ollama")` raised `ValueError` and crashed
  every `st-*` tool immediately after generating. New internal `_make_for(ai_key)`
  helper: if `ai_key` is already an `AI_HANDLER_REGISTRY` key (a raw make) it is
  used directly, otherwise it is resolved as an agent. Wired into all five
  helpers, with a regression test. (This shipped in 0.11.0 but was omitted from
  the original changelog entry — documented retroactively 2026-07-18.)

### Notes
- The legacy `CROSS_AI_ALIASES_FILE` environment variable remains **ignored**
  for path resolution (use `CROSS_AI_AGENTS_FILE`); setting it still emits a
  one-time `DeprecationWarning`. The `_alias` response field and the on-disk
  `alias` schema key retain their spelling for data back-compat (intentionally
  out of scope).
- Paired with **cross-st 0.12.0**, which removes its own `_alias_admin` shim and
  the hidden `--*-alias` CLI flags, and bumps its floor to
  `cross-ai-core[all]>=0.11.0`.

---

## [0.10.0] — 2026-07-16  *(Ollama local/LAN provider)*

Additive, fully backward-compatible minor release. Adds Ollama as the first
**local** and first **keyless** provider. Nothing in the existing public API
changes; the AGT-9 `aliases.py` deprecation shim is **still present** (its
removal moves to 0.11.0 so this additive feature stays decoupled from that
breaking cleanup).

### Added
- **Ollama local/LAN provider (OLL-1 / OLL-2, Phase 1).** New
  `cross_ai_core/ai_ollama.py` implements `OllamaHandler(BaseAIHandler)`
  talking to the Ollama HTTP API (`POST /api/generate`, non-streaming).
  Registered in `AI_HANDLER_REGISTRY` and appended to `AI_LIST` as
  `"ollama"`.  Configured entirely via env vars (no API key on a trusted
  network): `OLLAMA_BASE_URL` (default `http://localhost:11434`),
  `OLLAMA_MODEL` (default `llama3.1`), `OLLAMA_API_TOKEN` (optional bearer
  for reverse-proxied setups), `OLLAMA_REQUEST_TIMEOUT` (default 120 s).
  Network failures map to `ConnectionError` / `TimeoutError` / `RuntimeError`
  with actionable messages.  `get_usage()` returns real token counts from
  Ollama's `prompt_eval_count` / `eval_count`.
- **Ollama connectivity + discovery helpers (OLL-3, Phase 2).**
  `OllamaHandler.health_check()` (bool, never raises), `require_healthy()`
  (raises `ConnectionError` with a hint), and `list_models()` (installed
  model tags from `/api/tags`, `[]` on failure — feeds st-admin discovery).
  New `OLLAMA_HEALTH_CHECK_TIMEOUT` env var (default 5 s) for a fail-fast
  connectivity probe.  AGENTS.md gains an "Ollama (local/LAN provider)"
  section including remote-host setup (`OLLAMA_HOST=0.0.0.0`, firewall,
  mDNS `.local`) and troubleshooting.
- **Ollama concurrency cap (OLL-4, Phase 4.1).**
  `get_rate_limit_concurrency("ollama")` now returns a conservative
  hardware-bound default of **2**, tunable per-machine via the new
  `OLLAMA_MAX_CONCURRENCY` env var (empty / non-numeric / non-positive
  values fall back to the default; the override never affects other makes).
- 43 tests total for the provider + concurrency (`tests/test_ai_ollama.py`
  and the Ollama cases in `tests/test_ai_handler.py`, all HTTP mocked — no
  daemon needed in CI).

### Notes
- Ollama is the first **keyless** provider, so it is intentionally absent
  from `PROVIDER_API_KEY_ENV`; the API-key coverage invariants now scope to
  keyed providers only.
- Downstream (`cross-st`) enablement — `st-admin` agent discovery, `st.py`
  rotation, `st-cross` parallel matrix — is tracked separately as the
  OLL-CST series and targets a dedicated cross-st cut.

---

## [0.9.0] — 2026-05-10  *(AGT-9 alias → agent cleanup)*

Cleanup-only release that completes the rename started by Agents v2 in
0.8.0.  Pairs with `cross-st 0.11.0`.  No behavioural change beyond the
two deprecation warnings noted below — anything that worked in 0.8.0
keeps working unmodified for one release via the back-compat shim.

### Renamed
- **Module**: `cross_ai_core.aliases` → `cross_ai_core.agents`.  The
  legacy import path (`from cross_ai_core.aliases import …`) still
  works for one release via a thin shim that emits a
  :class:`DeprecationWarning` on import.  Removed in 0.10.0.
- **Symbols** (legacy names kept as back-compat assignments inside
  `agents.py`, also still re-exported from the top-level
  `cross_ai_core` namespace for one release):

  | Old (deprecated) | New |
  |---|---|
  | `AliasSpec` | `AgentSpec` |
  | `_AI_ALIASES` | `_AGENTS` |
  | `_ALIAS_LOAD_ERROR` | `_AGENT_LOAD_ERROR` |
  | `_aliases_file_path()` | `_agents_file_path()` |
  | `_load_aliases()` | `_load_agents()` |
  | `reload_aliases()` | `reload_agents()` |
  | `resolve_alias()` | `resolve_agent()` |
  | `get_aliases()` | `get_agents()` |
  | `get_alias_load_error()` | `get_agent_load_error()` |

### Deprecated
- **Env-var `CROSS_AI_ALIASES_FILE`** is no longer honoured for path
  resolution; only `CROSS_AI_AGENTS_FILE` is consulted.  Setting the
  legacy var emits a one-time :class:`DeprecationWarning` directing
  the user to switch.  The legacy var read-path itself is removed
  entirely in 0.10.0.

### Tests
- `tests/test_aliases.py` → `tests/test_agents.py`.
- New `tests/test_legacy_aliases_shim.py` pins both the
  `DeprecationWarning` and the back-compat re-exports.
- `tests/conftest.py` autouse fixture renamed
  `_seed_legacy_alias_registry` → `_seed_legacy_agent_registry`; uses
  the new `_AGENTS` / `AgentSpec` / `reload_agents` symbols.

### Migration
External callers should switch import paths in this order:

1. Anything that did `from cross_ai_core.aliases import X` → change to
   `from cross_ai_core.agents import X` (or, for public names, simply
   `from cross_ai_core import X`).
2. Anything using `AliasSpec` / `resolve_alias` / `get_aliases` /
   `reload_aliases` / `get_alias_load_error` → replace with the
   `Agent…`-prefixed counterparts above.
3. Anyone setting `CROSS_AI_ALIASES_FILE` in their environment →
   rename to `CROSS_AI_AGENTS_FILE`.

---

## [0.8.0] — 2026-05-10  *(Agents v2 foundation)*

**Agents v2 (AGT-1a/b/c/d).**  First-class agents replace auto-seeded
aliases.  Ships paired with `cross-st 0.10.0`, which performs the
on-disk migration and the `--ai → --agent` CLI flag rename.

⚠️  **Breaking changes** — every consumer must define an agent before
calling any provider:

- `_load_aliases()` no longer auto-seeds one entry per built-in
  provider.  A fresh user with no `~/.cross_ai_models.json` gets an
  *empty* registry; `resolve_alias("anthropic")` now raises
  `ValueError("No agents defined.  Run 'st-admin --setup' (or
  'st-admin > AI > Manage > Add') to create one.")` instead of silently
  resolving to a self-alias.
- `resolve_alias()` no longer falls back to `AI_HANDLER_REGISTRY` for
  late-registered providers (the silent escape hatch used by some
  pre-AGT tests has been removed).
- `get_default_ai()` returns `None` when the registry is empty (was:
  hardcoded fallback to `AI_LIST[0]`).
- `get_ai_list()` returns `[]` when no agents are defined; it no longer
  pretends the 5 built-in makes are pre-registered.  Use
  `get_ai_make_list()` if you need the canonical built-in list.

### Added

- **`cross_ai_core/keys.py`** (AGT-1c) — single source of truth for
  provider API-key detection:
  - `PROVIDER_API_KEY_ENV: dict[str, tuple[str, …]]` — gemini accepts
    both `GEMINI_API_KEY` and `GOOGLE_API_KEY`; the first non-empty
    value wins.
  - `has_api_key(provider) -> bool` — value-only check; never makes a
    live API call.  Raises `ValueError` for unknown providers.
  - `api_key_env_var(provider) -> str` — canonical env-var name for
    diagnostics.
- **`cross_ai_core.aliases`** schema layer (AGT-1d):
  - `SCHEMA_VERSION = 2` constant.
  - Reader accepts both v1 (legacy flat dict, inner `make` key) and v2
    (envelope `{"version": 2, "agents": {...}, "_migrated_to_agents_v2": true}`,
    inner `provider` key).  When both `provider` and `make` are present
    on a record, `provider` wins.
  - `migrate_v1_to_v2(data: dict) -> dict` — pure-function helper that
    upgrades a v1 dict to the v2 envelope; idempotent on v2 input;
    skips inner specs that are not dicts or lack a provider key.
    Used by the cross-st AGT-2 migration.
  - `write_agents_file(agents, path=None) -> str` — atomic writer
    (temp file + `os.replace`); always emits the v2 envelope; preserves
    iteration order; rolls back the temp file on `json.dump` failure.
- **`cross_ai_core.aliases.get_agents()`** (AGT-1b) — preferred name
  for `get_aliases()` (alias kept for back-compat).
- **`CROSS_AI_AGENTS_FILE`** environment variable — preferred name for
  the alias-file override.  `CROSS_AI_ALIASES_FILE` is still honoured
  but takes lower precedence when both are set.
- **`DEFAULT_AGENT`** environment variable — preferred name for the
  default-provider override.  `DEFAULT_AI` is still honoured.

### Changed

- `_API_KEY_ENV_VARS` in `ai_handler` now derives from
  `keys.PROVIDER_API_KEY_ENV` so all key-detection surfaces agree.
- `check_api_key()` now uses `keys.has_api_key()` internally — gemini
  callers benefit from the multi-name (`GEMINI_API_KEY` /
  `GOOGLE_API_KEY`) check.
- Diagnostic messages reference *provider* / *agent* rather than
  *make* / *alias*.
- `resolve_alias()` typo-suggestion error message lists "Defined
  agents" (was: "Known").

### Tests

- 220 passing (was 196 in 0.7.1) — +24 net (new keys + schema +
  empty-registry coverage; legacy "auto-seeded built-ins" assertions
  rewritten to use `get_ai_make_list()`).
- New `tests/conftest.py` seeds the 5 built-in providers (plus the
  legacy mock-provider names used by `test_ai_handler`) for the test
  session, emulating the cross-st AGT-2 migration.

---



**Model discovery (CAC-10h).** Adds a single helper —
`get_available_models(make)` — that asks each provider's SDK what models the
caller's API key can actually reach, caches the result for 7 days, and falls
back to a curated `RECOMMENDED_MODELS` list whenever the live call fails.
Used by the upcoming `st-admin` alias-management wizard (CST-MM-i) so the
new-alias picker can show real, currently-available models without forcing
the user to memorise model id strings.

### Added
- **`cross_ai_core/discovery.py`** — new module:
  - `ModelInfo(id, family, is_chat, created_at, is_default, is_recommended)` dataclass with `to_json` / `from_json`.
  - `get_available_models(make, refresh=False) -> list[ModelInfo]` — single public entry point. Sorts recommended first (in curated order), then everything else newest-first.
  - Per-provider list-and-filter functions for openai (deny-list filter on embeddings/whisper/tts/dall-e/fine-tunes), anthropic (`claude-` prefix), xai (`grok-` prefix), gemini (`generateContent` capability filter, strips `models/` prefix), perplexity (best-effort, sparse endpoint).
  - 7-day disk cache in `~/.cross_models_cache/<make>.json`; override directory with `CROSS_MODELS_CACHE_DIR`; bypass entirely with `CROSS_NO_MODELS_CACHE=1`. Atomic write via `os.replace`; corrupt cache files self-heal.
  - Graceful degradation: any exception during the live call → curated `RECOMMENDED_MODELS` returned. **Discovery never raises to the caller.**
  - Live results spliced with curated entries — recommended ids hidden by a patchy SDK still surface in the wizard.
  - `MODELS_CACHE_TTL_SECONDS = 604800` exported for callers that want to mirror the policy.
- **`cross_ai_core/recommendations.py`** — new module:
  - `RECOMMENDED_MODELS: dict[str, list[str]]` — curated per-make list. First entry is treated as that make's default.
  - `get_recommended(make)` / `get_recommended_default(make)` helpers.
  - This file is the canonical place to surface a new flagship model — bump the dict, cut a patch release.

### Changed
- `cross_ai_core/__init__.py` — exports `ModelInfo`, `get_available_models`, `MODELS_CACHE_TTL_SECONDS`, `RECOMMENDED_MODELS`, `get_recommended`, `get_recommended_default`.

### Tests
- `tests/test_discovery.py` — **21 new tests**: ModelInfo round-trip, per-provider filter behaviour (5 providers), 7-day TTL fresh/stale/refresh, env-var disable, corrupt cache recovery, annotation, sort order, splice-in, fallback on API error, unknown-make handling, package exports.
- **196 passed** (was 175 at 0.7.0).

---



The **multi-model alias layer** (CAC-10). Adds a thin user-facing alias
namespace (e.g. `anthropic-opus`, `anthropic-sonnet`) that resolves to
`(make, model)` pairs, so callers can reference more than one model per
provider without changing the on-disk container schema or the `--ai` CLI
surface. Every existing make string is auto-aliased to itself with
`model=None`, so legacy callers and pre-0.7.0 container files keep working
byte-for-byte.

### Added
- **`cross_ai_core/aliases.py`** — new module:
  - `AliasSpec(make, model)` namedtuple.
  - `~/.cross_ai_models.json` loader (override path with
    `CROSS_AI_ALIASES_FILE`); seeds one self-alias per built-in make and
    merges user definitions on top in declaration order.
  - `resolve_alias(alias) -> AliasSpec` with `did_you_mean()` typo
    suggestions; falls through to `AI_HANDLER_REGISTRY` for late-registered
    providers (test mocks, plug-in handlers).
  - `get_aliases()`, `get_alias_load_error()`, `reload_aliases()`,
    `did_you_mean()`.
  - `get_rate_limit_group(alias) -> (group_key, cap)` — group key is the
    resolved make so multiple aliases sharing a make share one semaphore.
- **`get_ai_make_list()`** — built-in make list (no aliases), useful when an
  alias-management wizard needs to show the user a "pick a provider" picker
  separate from the `--ai` choices.
- `process_prompt()` now stamps `_alias` and `_model` alongside the existing
  `_make` on every returned response (in-memory only — never written to the
  cache file).

### Changed
- **`get_ai_list()`** now returns alias keys (not raw makes). Backward-
  compatible because every built-in make is auto-registered as a self-alias.
- **`get_ai_make()`, `get_ai_model()`, `get_default_ai()`, `get_content()`,
  `put_content()`, `get_data_content()`, `get_data_title()`, `get_usage()`,
  `check_api_key()`, `reset_client_cache()`** — all resolve alias → make
  before dispatch.
- `get_ai_model(alias)` resolution order: explicit `model=` kwarg →
  `<ALIAS_UPPER>_MODEL` env var (dashes → underscores; e.g.
  `ANTHROPIC_OPUS_MODEL`) → `<MAKE_UPPER>_MODEL` env var (legacy) → alias
  spec model → handler default. (CAC-10f)
- The per-provider client cache is keyed on the **resolved make**, so two
  aliases sharing a make share one SDK client and one connection pool.
  Confirmed by `TestAliasesShareClient` (1 construction, 2 calls).
- `resolve_alias()` raises `ValueError(f"Unsupported AI model: {bad!r}. Did
  you mean {suggestion!r}? …")` — keeps the legacy `Unsupported AI` prefix
  so existing grep / test patterns continue to match.

### Tests
- New `tests/test_aliases.py` — 31 tests covering loader, collision
  rejection, resolver, did-you-mean, rate-limit-group sharing, alias
  stamping in `process_prompt`, env-var override chain, client-cache sharing
  across aliases, and `get_ai_list` / `get_default_ai` alias-awareness.
- All 144 pre-existing tests stay green. Total: **175 passing**.

### Migration notes for consumers
- No code changes required for callers that only use built-in make strings
  (`"xai"`, `"anthropic"`, …) — those keep working unchanged.
- To add user aliases, drop a `~/.cross_ai_models.json` file:
  ```json
  {
    "anthropic-opus":   {"make": "anthropic", "model": "claude-opus-4-5"},
    "anthropic-sonnet": {"make": "anthropic", "model": "claude-sonnet-4-5"}
  }
  ```
- `cross-st 0.9.0` consumes this layer for the multi-model `st-cross` matrix
  (CST-MM series).

---

## [0.6.0] — 2026-04-17

This release rolls up the CAC-1 → CAC-9 hardening series. Headline changes:
the on-disk cache is now atomic + lock-protected, every SDK client is
constructed lazily and cached per-process, `process_prompt()` accepts a
`retry_budget`, and a new `get_rate_limit_concurrency()` helper exposes
recommended per-provider semaphore sizes (consumed by `cross-st`'s PAR-1
`st-cross --parallel` mode).

### Added
- **`get_rate_limit_concurrency(make) -> int`** — recommended max concurrent
  in-flight calls per provider. Defaults: `xai=3, anthropic=2, openai=3,
  perplexity=2, gemini=5`. Raises `KeyError` on unknown provider. Exported
  from the package root. (CAC-5)
- **`retry_budget` kwarg** on `process_prompt()` and the underlying
  `retry_with_backoff()` — caps total time spent retrying transient errors.
  Each backoff sleep is shortened to `min(wait, remaining)`; loop exits as
  soon as the budget hits zero. `retry_budget=0` disables retries entirely;
  `None` (default) preserves pre-0.6 unlimited-retry behaviour. (CAC-4)
- **`"timeout"` keyword** added to `TRANSIENT_ERROR_KEYWORDS` — `httpx.ReadTimeout`,
  `APITimeoutError`, and similar are now classified as transient and retried
  rather than surfacing immediately. (CAC-4)
- **Lazy + cached SDK clients per provider** — `process_prompt()` constructs
  each provider client at most once per process, behind a `threading.Lock`
  with double-checked locking. Cache hits no longer construct a client at
  all (factory lambda only invoked on miss / `use_cache=False` /
  `CROSS_NO_CACHE`). New `process_prompt(..., client=...)` kwarg lets callers
  inject explicit clients (e.g. test mocks). (CAC-8)
- **`reset_client_cache(make=None)`** — public helper to drop one or all
  cached clients. Required for test isolation, key rotation, and post-fork
  cleanup. Exported from `__init__.py`.
- **`CROSS_NO_CLIENT_CACHE=1`** env var — fully disables the SDK client
  cache (mirrors `CROSS_NO_CACHE` for response caching).
- **`AIResponse.__repr__`** — concise debug string showing model, cached/live
  flag, and a truncated content preview. (CAC-6)
- **96 new tests** — `TestCacheAtomicWrite`, `TestGetAiList`,
  `TestTimeoutIsTransient`, `TestRetryBudget`, `TestGetRateLimitConcurrency`,
  `TestAIResponseRepr`, `TestClientCache` (8 tests including a
  `threading.Barrier` race that proves only one client is constructed under
  concurrent first-use). 144 total, all pass.

### Changed
- **Cache writes are now atomic + lock-protected** — `BaseAIHandler` writes
  the cache file via temp-file + `os.rename()` (atomic on POSIX) under
  `fcntl.LOCK_EX`. Reads acquire `fcntl.LOCK_SH`. Corrupt cache files
  (`json.JSONDecodeError`/`OSError`) are now caught, deleted, and the call
  falls through to the live API instead of crashing the subprocess. Windows
  build falls back gracefully if `fcntl` is unavailable (no-op). (CAC-1)
- **`get_ai_list()` returns a copy** — `return list(AI_LIST)` — so mutating
  the return value no longer corrupts the global. Order is asserted as
  `["xai", "anthropic", "openai", "perplexity", "gemini"]`. (CAC-3)
- **`DEFAULT_SYSTEM`, `MAX_TOKENS`, `get_title()` lifted to
  `BaseAIHandler`** — duplicates removed from all 5 provider files
  (−79 lines). `get_title()` is now a concrete classmethod (was abstract).
  Module-level payload helpers reference the base-class constants. (CAC-7)
- **Type annotations tightened** — `BaseAIHandler.get_payload()` gains a
  `-> dict` return type; `str  None` annotation corrected to `"str | None"`.
  (CAC-6)

### Fixed
- **`NameError: name 'DEFAULT_SYSTEM' is not defined` in gemini provider** — CAC-7
  lifted `DEFAULT_SYSTEM` to `BaseAIHandler` and removed the local constant from all
  five provider files, but one call site in `GeminiHandler._call_api()` (the
  `payload.get("system_instruction", DEFAULT_SYSTEM)` fallback argument) was missed.
  Every gemini API call raised a `NameError` and was reported as a failure in
  `st-cross` Step 1. Fixed by replacing the bare name with
  `BaseAIHandler.DEFAULT_SYSTEM`. (`d788e69`)


- Stray commented `base_url="https://api.x.ai"` artifact in
  `ai_anthropic.py` `get_anthropic_client()`. (CAC-9)

### Notes for consumers
- **`cross-st` requirement bumps to `cross-ai-core>=0.6.0`** to use the new
  `get_rate_limit_concurrency()` helper from PAR-1.
- **Cache layer is fork-aware but not fork-safe across providers** — call
  `reset_client_cache()` after `os.fork()` to be safe. PAR-1 dodges this by
  using subprocesses (each child gets its own clean cache) — intentional.

---



### Added
- `model=` keyword parameter on `process_prompt()` — per-call model override.
  Resolution order: explicit `model` arg → `<AI_KEY_UPPER>_MODEL` env var → handler
  default (e.g. `gemini-2.5-flash`).  Setting `GEMINI_MODEL=gemini-2.5-pro` in
  `~/.crossenv` globally switches the model without touching code.
- `get_ai_model(make)` now checks the `<MAKE_UPPER>_MODEL` env var before returning
  the compiled-in handler default — same resolution order as `process_prompt()`.
- 11 new tests covering model override paths in `TestProcessPromptModel` and
  `TestGetAiModel` (105 total, all passing).

### Changed
- **Provider SDK minimums bumped** (openai is a major version break):
  - `openai>=2.0.0` (was `>=1.70.0`) — tested on openai 2.31.0
  - `anthropic>=0.86.0` (was `>=0.84.0`) — tested on anthropic 0.92.0
  - `google-genai>=1.69.0` (was `>=1.65.0`) — tested on google-genai 1.71.0
- `process_prompt()` docstring expanded to document all keyword parameters
- `get_ai_model()` docstring updated to describe env-var resolution order

---

## [0.4.2] — 2026-04-08

### Added
- `get_content_auto(response)` — extracts text from a self-describing response using the `_make` key stamped by `process_prompt()`; raises `ValueError` if `_make` is absent
- `put_content_auto(report, response)` — updates text in a self-describing response the same way; raises `ValueError` if `_make` is absent
- `process_prompt()` now stamps `"_make": ai_key` into every `dict` response it returns (in-memory only — the on-disk cache is unchanged), making responses self-describing for the `_auto` helpers
- `retry_with_backoff()` exported from the public API (was implemented in 0.4.0 but inadvertently omitted from `__init__.py`)

---

## [0.4.1] — 2026-04-03

### Added
- `CROSS_NO_CACHE=1` environment variable support — set in `~/.crossenv` or `.env` to bypass the on-disk API response cache globally, without requiring `--no-cache` on every command. Takes priority over `use_cache=True` passed to `process_prompt()` / `get_cached_response()`.

---

## [0.4.0] — 2026-04-02

### Added
- `system=` keyword parameter on `process_prompt()` — override the provider's default system prompt per call; `None` falls back to the provider's built-in default
- `QuotaExceededError`, `RateLimitError`, `TransientError`, `CrossAIError` added to the public API (`__all__`)
- `retry_with_backoff()` added to the public API
- `get_usage()` — normalised token-count extraction across all providers
- `check_api_key()` — diagnostic helper that prints which `.env` files were searched and the exact env var to add
- `AIResponse.was_cached` attribute — know whether a response was served from disk cache
- `py.typed` PEP 561 marker — package is now recognised as typed by mypy / pyright
- `[tool.pytest.ini_options]` in `pyproject.toml` — test config consolidated
- `Documentation` URL in `pyproject.toml` → `docs/` folder
- `docs/api-reference.md` — full public API reference with parallel-call examples
- `docs/providers.md` — per-provider guide (model, API key, strengths, free tier)
- `COMMERCIAL_LICENSE.md`

### Fixed
- `BaseAIHandler` ABC now enforces all 9 required abstract methods (previously only 3)
- `_get_cache_dir` exported publicly as `get_cache_dir` alias (private name convention conflict resolved)
- `use_cache` default was `False` in OpenAI and Perplexity providers — now consistently `True` across all five
- `get_ai_make()` and `get_ai_model()` now raise `ValueError` on unknown key instead of `AttributeError`
- `__version__` now read from `importlib.metadata` — single source of truth in `pyproject.toml`
- `get_data_title` type hint corrected from `json` (module) to `dict`
- `load_dotenv("~/.crossenv")` in README corrected to `os.path.expanduser("~/.crossenv")` — tilde was not expanded by python-dotenv

### Changed
- `verbose` and `use_cache` are now keyword-only arguments on `process_prompt()` (enforced by `*,`)

---

## [0.3.0] — 2026-03 *(initial public release)*

### Added
- Five providers: `xai`, `anthropic`, `openai`, `perplexity`, `gemini`
- MD5-keyed response caching via `~/.cross_api_cache/`
- `AIResponse` wrapper with backward-compatible 4-tuple unpacking
- `handle_api_error()` — classifies quota / rate-limit / transient errors
- Optional-extras install model (`[anthropic]`, `[gemini]`, `[openai]`, `[xai]`, `[all]`)

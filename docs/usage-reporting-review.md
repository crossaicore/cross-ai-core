# Usage reporting implementation review

November 5, 2026. Implemented against `37cf0ad`, with `2026.11.0` prepared as an
unreleased version. The implementation is prepared for pull-request review and
local package validation. PyPI publication, TwoScale integration and production
deployment remain separate steps.

## Result

`get_usage_report()` returns a standard-library `UsageReport` for the six existing
providers. It distinguishes unknown counts from measured zero, includes documented
cache and thinking contributions, retains native usage metadata, and flags
inconsistencies. It performs no token counting, provider calls or file I/O.
See the [API reference](api-reference.md#get_usage_report) and
[design](usage-reporting-design.md).

The implementation uses existing provider/agent resolution. Common validation
lives in one small module. OpenAI/Perplexity share their Chat Completions mapping;
Anthropic/xAI share their Messages mapping. One concrete base-class wrapper
replaces six duplicated legacy `get_usage()` implementations. Existing third-party
overrides still work; the new method has a non-abstract fallback. There are no
new runtime dependencies, configuration switches or accounting services.

Gemini now retains nested SDK usage metadata alongside the original response
keys. Its conversion preserves valid text when usage is absent or has an
unexpected JSON shape. This was a robustness gap found during implementation
review and is covered by regression tests.

## Initial offline test results

The original suite passed all 274 tests before changes. The new suite contains
153 additional cases, for 427 total. Every suite below ran with socket connections
blocked; provider calls were mocked. No paid AI requests were made.

| Environment | Result |
|---|---|
| Python 3.10.22, source checkout | 427 passed |
| Python 3.11.18, source checkout | 427 passed |
| Python 3.12.13, source checkout | 427 passed |
| Python 3.12.13, installed wheel outside the source tree | 427 passed |
| Python 3.10.22, wheel with only required dependencies | All 8 provider fixtures passed; no provider SDK or tokenizer installed |

Wheel and source archive builds passed. The wheel contains the new API and
`2026.11.0` metadata; its required dependency list is unchanged. The source
archive includes the JSON test fixtures through `MANIFEST.in`.

Coverage includes all supported usage envelopes, real Gemini and Anthropic SDK
serialization, missing/null/malformed metadata, explicit zero, invalid integer
types, large counts, contradictory totals, cache/reasoning subsets, old Gemini
cache entries, agent dispatch, custom handlers, tuple compatibility, detached
raw metadata and local response reuse. Six deterministic mixed-input tests
exercise 1,200 combinations of valid and malformed aggregate counters.

To repeat the normal suite, install the development and provider extras in this
repository's own virtual environment, then run:

```bash
.venv/bin/python -m pytest tests/ -q
```

The added usage tests block sockets and SDK client construction themselves.
For a fully offline run, the review also wrapped `pytest.main()` in mocks of
`socket.socket.connect` and `socket.create_connection` that raise on access.

## Robustness and compatibility findings

- Missing measurements stay unknown. Invalid optional details do not discard
  usable aggregates. Conflicting valid measurements remain inspectable with
  `inconsistent` status; invalid supplied totals are not silently replaced.
- Cache reads/writes are input subsets and reasoning is an output subset. They
  are never added twice. A locally reused response retains historical usage;
  callers still use `AIResponse.was_cached` to avoid recording a new charge.
- Raw metadata is detached from the response and excluded from the record's
  representation. An excessively deep extra field cannot discard valid counts.
  Consumers remain responsible for storage bounds and access to raw metadata.
- The legacy three-integer dictionary and `AIResponse` constructor/tuple remain
  compatible. Corrected counts can differ from earlier releases; unknown values
  become zero only in the legacy API. Release notes describe these differences.

## Remaining limits and review boundary

The initial tests establish offline extraction and compatibility, not live provider
availability or invoice accuracy. Fixtures are synthetic and cite the primary
schema sources. Python 3.13 and later were not tested in this review.

Old Gemini cache entries cannot recover details that were already discarded.
An unexplained total gap is reported as partial usage. Perplexity's native cost,
search and additional token categories are retained without guessing their
relationship to normalized totals. The exact xAI Messages endpoint has a
documented mapping but is deprecated; transport migration is separate work.

No new implementation defect remains identified within this scope. Application
accounting still needs its own implementation and tests: persistence, missing
usage policy, cost estimates, limits and crash/retry handling are not library
responsibilities. TwoScale's existing tokenizer-related behavior is unchanged.
Package publication and TwoScale integration remain pending review.

## Follow-up: optional real-world check

At the owner's request, added a separate opt-in
[live smoke command](live-usage-smoke.md). Its dry-run default performs no request;
`--live` makes one small, uncached request with SDK retries disabled. The normal
pytest suite remains offline.

The November 5 live run passed for OpenAI, Anthropic, xAI and Perplexity. Native
metadata was inspected against the normalized counts, including xAI's nonzero
provider cache read. Gemini returned HTTP 402 because prepaid credits are
depleted; no generated response or usage could be validated for that provider.
No requests were retried. See the linked results for models, token counts and
the recorded native metadata. This provides live evidence for those specific
requests without extending the result to every model or usage category.

The expanded offline suite passes all 446 tests on Python 3.10.22, 3.11.18 and
3.12.13 with socket connections blocked. The 19 added cases cover dry-run
behavior, small request limits, disabled retries, failure diagnostics and replay
of the four reviewed live metadata samples. Wheel/source builds pass; the source
archive includes the optional command and its test fixtures. No production
library behavior changed in this follow-up.

A subsequent CLI usability fix adds explicit `--env-file ~/.crossenv` loading
through the development dependency `python-dotenv`. File loading occurs before
library initialization and preserves exported values. All 452 offline tests pass
on Python 3.11.18; a network-blocked dry run using the owner's actual file confirms
credentials are detected. No additional paid request was made for this fix.

Fresh checks through the credential-file CLI passed for Anthropic, xAI and
Perplexity after the owner confirmed OpenAI. Gemini remains blocked by depleted
credits. Initial Ollama discovery was blocked because neither hostname resolved
from the development Mac and no service answered on the cached LAN neighbors.
See the [follow-up results](test-results/usage-smoke-recheck-20261105.json). No
additional runtime code changes or automatic retries were needed for these checks.

Local-server follow-up resolved access through SSH forwarding: m2mac runs Ollama,
and flik runs LM Studio. Ollama passed with 34 input and 2 output tokens. LM Studio
initially used the entire 128-token cap for reasoning; a deliberate 512-token
follow-up returned `OK`, 34 input and 178 output tokens, with 174 reasoning tokens
already included in output. Both metadata formats normalize correctly. Native
samples and the reasoning-only failure are now regression fixtures. See
[local-server instructions and results](live-usage-smoke.md#local-servers-through-ssh-forwarding).
Gemini's depleted credits are the remaining live-provider validation blocker.
After adding these four regression cases, all 456 offline tests pass on Python
3.11.18 with socket connections blocked. No production library code changed for
the local-server checks.

Package preparation also includes all Python test support files in the source
archive, including `tests/conftest.py` and `tests/__init__.py`, so packaged tests
have the same fixtures and imports as the checkout. No runtime dependency or
provider behavior changed for this packaging correction.

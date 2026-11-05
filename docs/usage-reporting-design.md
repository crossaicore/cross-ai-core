# Unified AI usage reporting design

Status: implemented for review, November 5, 2026. No release or TwoScale
integration has been performed. See [implementation review](usage-reporting-review.md).
Implementation baseline: cross-ai-core `37cf0ad`, package `2026.10.0`.
The design below records the agreed scope; current API details are in the
[API reference](api-reference.md#get_usage_report).

cross-ai-core will interpret provider usage metadata once and expose a common
record to its consumers. Applications will own persistence, spending limits and
cost estimates. Generation will not depend on a local tokenizer, a downloaded
pricing catalogue, or a separate accounting service.

The first consumer is TwoScale. Its coordinated design is
`~/github/twoscale/docs/architecture/ai-usage-accounting-design.md`. The public
interface must also preserve existing cross-st and third-party callers.

## Scope and ownership

| Responsibility | Owner |
|---|---|
| Interpret each supported response format and token category | cross-ai-core provider handlers |
| Represent unknown values and inconsistent metadata | cross-ai-core common usage record |
| Preserve the provider's usage metadata | cross-ai-core, with application storage bounds |
| Identify local response reuse | Existing `AIResponse.was_cached`; TwoScale's own cache |
| Associate a network attempt with a report/job | Calling application |
| Persist usage and enforce configured limits | Calling application |
| Calculate a dollar estimate from configured rates | Calling application in this release |

Use the six existing providers and their existing endpoints. This work does not
change model selection, credentials, retries, streaming support, or the cache
storage implementation. Provider token counts remain provider measurements;
normalizing field names does not make tokens equivalent across models.

## Current problems

`ai_handler.get_usage()` delegates to the provider handler and promises three
integer fields, defaulting missing values to zero. That contract is convenient
for old displays but unsuitable for accounting.

Offline examples against the baseline reproduce these problems:

| Response | Current result | Required interpretation |
|---|---|---|
| OpenAI response without usage | All counts zero | Counts unknown |
| Anthropic input 50, cache read 1,000, cache write 200, output 30 | Input 50, total 80 | Input 1,250, output 30, total 1,280 |
| Flattened Gemini prompt 100, candidates 20, thoughts 30, total 150 | Input 100, output 20, total 150 | Output includes the 30 thinking tokens |

Gemini's SDK conversion currently drops usage details before callers can inspect
them. TwoScale compensates for some provider differences in its own adapter,
creating two places that must change when a provider changes its response.

## Public interface

Add one public function and one standard-library dataclass:

```python
get_usage_report(ai_key: str, response: dict) -> UsageReport
```

Resolve provider names and configured agent names through the existing registry
and `_make_for()` path. A genuinely unknown provider name raises `ValueError`, as
`get_content()` does. A registered provider with absent or malformed metadata
returns a report describing what is known; it does not raise for that metadata.

`UsageReport` contains the following fields. The table records the agreed API
contract.

| Field | Type | Meaning |
|---|---|---|
| `provider` | `str` | Resolved registry make |
| `model` | `str \| None` | Model reported by the provider; never silently replaced with the requested model |
| `input_tokens` | `int \| None` | All input, including provider cache reads and writes and documented additional input categories |
| `output_tokens` | `int \| None` | All generated output, including reasoning when the format identifies it |
| `total_tokens` | `int \| None` | Provider total, or the sum of known input and output when the provider omits a total |
| `cache_read_tokens` | `int \| None` | Subset of input served by the provider's prompt cache |
| `cache_write_tokens` | `int \| None` | Subset of input written to the provider's prompt cache |
| `reasoning_tokens` | `int \| None` | Subset of output used for reasoning |
| `status` | `str` | `complete`, `partial`, `missing`, or `inconsistent` |
| `issues` | `tuple[str, ...]` | Stable diagnostic codes, with field names where useful; no provider message text |
| `raw_usage` | `dict \| None` | Detached copy of the usage object, or the known usage fields from a flat response |

Use `dataclasses.asdict()` for application serialization. Do not add a custom
serializer, plugin framework, price model, or mutable global accumulator.
Store the schema version in an application's persisted envelope, rather than
requiring library callers to negotiate versions.

The object is a passive record. Keep common validation in `usage.py`; keep
provider field mappings in their existing handler modules. This removes real
duplication while keeping an unfamiliar provider easy to inspect in one file.

Add a concrete `BaseAIHandler.get_usage_report()` default that returns missing
usage with an `unsupported_usage_format` issue. Existing external subclasses
must remain instantiable without implementing a new abstract method. Built-in
handlers override it. The public dispatcher and handlers use the same record.

## Counting and validation rules

1. Accept nonnegative integers, including explicit zero. Reject booleans,
   negative values, floats and numeric strings as counts. Preserve malformed
   values only in private raw metadata; the normalized field becomes `None`.
2. Unknown is `None`. An omitted breakdown is not automatically a measured
   zero. A documented optional contribution may be treated as zero when adding
   totals, without claiming the provider separately measured that breakdown.
3. Cache read/write counts are input subsets. Reasoning is an output subset.
   Consumers must never add these breakdowns to the normalized totals again.
4. Derive a missing total only when both aggregate counts are known. Do not
   invent a missing input/output count by subtracting unrelated fields.
5. Preserve a valid provider total even when it disagrees with the normalized
   parts. Return `inconsistent` and `total_mismatch`; do not silently repair it.
6. If cache subsets exceed input, or reasoning exceeds output, retain valid
   aggregate counts, mark the conflicting breakdown unknown, and report the
   inconsistency. Aggregates remain inspectable, not automatically billable.
7. Unknown extra usage fields remain in `raw_usage`; their presence alone is
   not an error. They must not be counted without a documented mapping.
8. Do not log prompts, responses or raw metadata during normalization. The
   function performs no network, tokenizer, environment-file or cache I/O.

`complete` means input/output and their total are consistent. Optional breakdowns
may be unknown. `partial` means aggregate data is absent or malformed but some
usable measurements remain. `missing` means no usable aggregate data is
available. Contradictory valid measurements take precedence as `inconsistent`.
An invalid supplied optional field adds an issue without erasing valid totals.

Initial issue codes: `usage_missing`, `unsupported_usage_format`,
`invalid_count:<field>`, `total_derived`, `total_mismatch`,
`breakdown_exceeds_total:<field>`, `legacy_usage_incomplete`, and
`raw_usage_unavailable`.
Informational `total_derived` does not make an otherwise complete record partial.

## Provider mappings

Support the response formats actually consumed by the current handlers and
TwoScale. Tests must identify the endpoint and response shape; a provider name
alone is not evidence that another endpoint has identical counting rules.

| Handler and format | Normalized input | Normalized output | Details |
|---|---|---|---|
| OpenAI Chat Completions | `usage.prompt_tokens` | `usage.completion_tokens` | Read cached and reasoning subsets from the corresponding details objects; do not add them again |
| Anthropic Messages | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` | `output_tokens` | Cache fields are additional input; thinking is already within output |
| Gemini REST / SDK dictionary | `promptTokenCount + toolUsePromptTokenCount` | `candidatesTokenCount + thoughtsTokenCount` | Recognize camelCase and SDK snake_case; cached content is already in prompt count |
| xAI Messages currently used by this package | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` | `output_tokens` | Anthropic-compatible Messages schema; exact endpoint evidence is recorded below |
| Perplexity current Chat Completions | `usage.prompt_tokens` | `usage.completion_tokens` | Preserve search/cost metadata; do not assume tokens describe every billable item |
| Ollama `/api/generate` | `prompt_eval_count` | `eval_count` | Missing counts stay unknown; local inference is not a cloud-token invoice |

OpenAI's output count includes non-visible generation, so counting visible text
again cannot reproduce it. See [OpenAI token usage](https://developers.openai.com/api/docs/guides/token-counting).
Anthropic explicitly separates ordinary input from cache reads/writes. See
[Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).
Gemini documents prompt, candidate, thinking and tool-use contributions in its
[SDK usage type](https://github.com/googleapis/python-genai/blob/main/google/genai/types.py).
Ollama supplies evaluation counts in its [generate response](https://docs.ollama.com/api/generate).

### Gemini compatibility

`get_json_response()` will retain a nested SDK `usage_metadata` dictionary
alongside its existing top-level fields. Serialize with the SDK's public JSON
conversion; handle absent usage metadata without failing text extraction.
Keep `model_version`, `text`, and existing flat fields for old consumers.

Prefer nested metadata when present. Old cache entries may contain only the
three flat counts. Read those entries without rewriting or evicting them. If
their total exceeds the known prompt and candidate counts and no breakdown
explains it, retain the provider total, set aggregate output to unknown, and
return `partial` with `legacy_usage_incomplete`. Keep the candidate count in raw
metadata; do not assert that every unexplained token was thinking. Preserve
explicitly supplied flat thinking/cache fields when they exist.

### Endpoint evidence

The exact [xAI Messages reference](https://docs.x.ai/developers/rest-api-reference/inference/legacy)
identifies the endpoint as Anthropic-compatible and supplies the cache input
fields. Its handler shares the Messages usage mapping. This endpoint is marked
deprecated; migration is separate work, and no live availability claim is made.

Perplexity's [SDK usage schema](https://github.com/perplexityai/perplexity-py/blob/main/src/perplexity/types/shared/usage_info.py)
identifies the current Chat Completions counters and native cost/search fields.
The tests retain those native fields. Top-level citation/reasoning categories are
not folded into totals or asserted to be subsets without documented semantics.

## Cache accounting

`UsageReport` describes the original provider response. It does not claim a new
request occurred. Consumers of `process_prompt()` must use `AIResponse.was_cached`
to decide whether a new call belongs in their spending ledger.

- A provider prompt-cache hit still incurs a provider request and can be charged.
- A cross-ai-core local response-cache hit incurs no new provider request. Its
  historical token metadata is still available, but must not be charged again.
- `get_usage_report()` has no cache-origin argument: raw usage cannot prove
  where the caller obtained the response. Keep that existing execution fact
  separate instead of guessing from cached-token counts.

No new `AIResponse` constructor arguments or tuple elements are needed. A
convenience `.usage` property is deferred; one extraction API is sufficient.

## Compatibility and pricing

Keep `get_usage()` and the handler method with exactly the existing three-key
integer dictionary. Built-in methods can use the new record internally, converting
unknown values to zero only for this legacy interface. Document that lossy
behavior and recommend the new function for accounting. Correct valid Anthropic
and Gemini totals through this wrapper; release notes must call out the changed
numbers. Unknown-provider behavior in the old function remains unchanged.

Preserve Python 3.10 support and the existing optional SDK dependencies. Add no
mandatory dependency for usage extraction. Keep configured models and agent
resolution unchanged. Adding a normalization method must not construct an SDK
client or require credentials.

Token reporting and price calculation are distinct. Retain provider-specific
dollar/currency metadata in `raw_usage`; this release does not automatically
declare those values an invoice. TwoScale continues to label rate-based costs
as estimates. [genai-prices](https://github.com/pydantic/genai-prices/tree/main/packages/python)
is a focused later option for usage extraction/pricing tables, and
[LiteLLM](https://docs.litellm.ai/docs/completion/token_usage) offers broader dispatch
and pricing. Existing handlers make an in-house change smaller for this scope.

## Planned changes and tests

| File | Planned change |
|---|---|
| `cross_ai_core/usage.py` | Passive record and shared count/consistency validation |
| `cross_ai_core/ai_base.py` | Concrete extension method, preserving third-party subclasses |
| Six `ai_<provider>.py` modules | Endpoint-specific extraction; legacy method delegates where appropriate |
| `cross_ai_core/ai_gemini.py` | Preserve SDK usage metadata and old response keys |
| `cross_ai_core/ai_handler.py`, `__init__.py` | Dispatch and public exports |
| `tests/test_usage_reporting.py` | New offline contract and provider cases |
| Existing handler/cache/compatibility tests | Confirm legacy APIs and response reuse |
| `docs/api-reference.md`, README, CHANGELOG | Document public API and changed valid counts |
| `pyproject.toml` | Next available CalVer release, at implementation/release time |

The test matrix must cover all six providers; absent/null/partial usage; explicit
zeros; invalid numeric types; inconsistent totals; cache subsets; reasoning
inclusion without double-counting; large valid integers; extra fields; raw input
not mutated; agent-name dispatch; custom handlers; and legacy dictionaries.
Use table-driven fixtures with endpoint/source references, not tests that only
repeat the implementation's arithmetic.

Gemini needs paired REST and SDK fixtures plus old flattened cache entries.
Cache tests must prove a local hit makes zero provider calls and leaves the
historical report intact. Patch client construction/network access to fail if
normalization touches either. Test Python 3.10 and the Python versions used by
TwoScale, without changing their environments during this design phase.

## Implementation and release sequence

1. Add endpoint fixtures and the contract tests, closing the xAI/Perplexity
   evidence gaps without paid calls.
2. Implement the common record and handler mappings; run the complete core suite.
3. Prepare a PR titled **Normalize provider usage with explicit missing counts**.
   Include compatibility behavior, provider mapping evidence and test results.
4. Build a local wheel and exercise TwoScale's integration in its separate test
   environment before publishing the core release. Check cross-st's existing
   usage consumers for compatibility without changing its runtime configuration.
5. After implementation is authorized and reviewed, merge, tag and publish using
   `RELEASE.md`; perform its TestPyPI trial. Pin TwoScale to the published release.

Acceptance: one provider-normalization path; correct tested totals/breakdowns;
unknown values survive the new API; old callers still work; no local tokenizer,
network lookup, pricing dependency or new service is required to read usage.

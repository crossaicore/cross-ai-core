"""Provider usage records and shared validation; no token counting or I/O."""
from copy import deepcopy
from dataclasses import dataclass, field


@dataclass(frozen=True)
class UsageReport:
    """Usage of the original response, including when it is reused locally.

    Cache counts are input subsets; reasoning is an output subset. Unknown
    counts are None. Check status/issues before using counts for accounting.
    Local reuse is identified separately by AIResponse.was_cached.
    """

    provider: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    status: str = "missing"
    issues: tuple[str, ...] = ()
    raw_usage: dict | None = field(default=None, repr=False)


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _count(data: dict, key: str, issues: list[str]) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if type(value) is not int or value < 0:
        issues.append(f"invalid_count:{key}")
        return None
    return value


def _sum_counts(*values: int | None) -> int | None:
    if any(value is None for value in values):
        return None
    return sum(values)


def _details(data: dict, key: str, issues: list[str]) -> dict:
    value = data.get(key)
    if value is not None and not isinstance(value, dict):
        issues.append(f"unsupported_usage_format:{key}")
    return _mapping(value)


def _report(
    provider: str, model, raw_usage, *, input_tokens=None, output_tokens=None,
    total_tokens=None, cache_read_tokens=None, cache_write_tokens=None,
    reasoning_tokens=None, derive_total=True, issues=(),
) -> UsageReport:
    """Finish a handler's validated counts without hiding inconsistencies."""
    issues = list(issues)
    if not isinstance(model, str) or not model.strip():
        model = None
    if total_tokens is None and derive_total:
        total_tokens = _sum_counts(input_tokens, output_tokens)
        if total_tokens is not None:
            issues.append("total_derived")
    inconsistent = False
    known_parts = sum(value for value in (input_tokens, output_tokens) if value is not None)
    if (total_tokens is not None and (total_tokens < known_parts or (
            input_tokens is not None and output_tokens is not None
            and total_tokens != known_parts))):
        issues.append("total_mismatch")
        inconsistent = True
    if input_tokens is not None:
        cache_total = (cache_read_tokens or 0) + (cache_write_tokens or 0)
        if cache_total > input_tokens:
            # Reads and writes partition input. Preserve evidence in raw_usage.
            if cache_read_tokens:
                issues.append("breakdown_exceeds_total:cache_read_tokens")
                cache_read_tokens = None
            if cache_write_tokens:
                issues.append("breakdown_exceeds_total:cache_write_tokens")
                cache_write_tokens = None
            inconsistent = True
    if (output_tokens is not None and reasoning_tokens is not None
            and reasoning_tokens > output_tokens):
        issues.append("breakdown_exceeds_total:reasoning_tokens")
        reasoning_tokens = None
        inconsistent = True
    aggregates = (input_tokens, output_tokens, total_tokens)
    if inconsistent:
        status = "inconsistent"
    elif all(value is not None for value in aggregates):
        status = "complete"
    elif any(value is not None for value in aggregates):
        status = "partial"
    else:
        status = "missing"
        issues.append("usage_missing")
    if isinstance(raw_usage, dict):
        try:
            raw_usage = deepcopy(raw_usage)
        except RecursionError:
            # An unusually deep extra field must not discard valid counters.
            raw_usage = None
            issues.append("raw_usage_unavailable")
    else:
        if raw_usage is not None:
            issues.append("unsupported_usage_format")
        raw_usage = None
    return UsageReport(
        provider, model, input_tokens, output_tokens, total_tokens,
        cache_read_tokens, cache_write_tokens, reasoning_tokens,
        status, tuple(dict.fromkeys(issues)), raw_usage,
    )

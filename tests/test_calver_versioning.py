"""CalVer ordering guards for the 0.x -> YYYY.M.R migration."""

from packaging.version import parse


def test_calver_orders_after_semver_line() -> None:
    """PEP 440 ordering keeps upgrades monotonic across the migration."""
    assert parse("2026.8.0") > parse("0.11.0")


def test_month_zero_padding_normalizes() -> None:
    """Writers should use unpadded months; parser treats both forms equally."""
    assert parse("2026.8.0") == parse("2026.08.0")


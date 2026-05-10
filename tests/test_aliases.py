"""tests/test_aliases.py — agent registry tests (CAC-10 + AGT-1)."""
import json
from unittest.mock import MagicMock

import pytest

import cross_ai_core
from cross_ai_core.aliases import (
    AliasSpec,
    SCHEMA_VERSION,
    did_you_mean,
    get_agents,
    get_alias_load_error,
    get_aliases,
    get_rate_limit_group,
    migrate_v1_to_v2,
    reload_aliases,
    resolve_alias,
    write_agents_file,
)
from cross_ai_core.ai_handler import (
    AI_HANDLER_REGISTRY,
    AI_LIST,
    _client_cache,
    get_ai_list,
    get_ai_make,
    get_ai_model,
    get_default_ai,
    process_prompt,
    reset_client_cache,
)
from cross_ai_core.keys import (
    PROVIDER_API_KEY_ENV,
    api_key_env_var,
    has_api_key,
)


@pytest.fixture
def alias_file(tmp_path, monkeypatch):
    path = tmp_path / "cross_ai_models.json"
    monkeypatch.setenv("CROSS_AI_AGENTS_FILE", str(path))
    monkeypatch.delenv("CROSS_AI_ALIASES_FILE", raising=False)
    reload_aliases()
    yield path
    monkeypatch.delenv("CROSS_AI_AGENTS_FILE", raising=False)
    reload_aliases()


def _write_v1(path, agents):
    path.write_text(json.dumps(agents))


def _write_v2(path, agents):
    envelope = {
        "version": 2,
        "agents": {
            n: {"provider": s["provider"], "model": s.get("model")}
            for n, s in agents.items()
        },
        "_migrated_to_agents_v2": True,
    }
    path.write_text(json.dumps(envelope))


@pytest.fixture(autouse=True)
def _isolate_client_cache():
    reset_client_cache()
    yield
    reset_client_cache()


class TestAliasSpec:
    def test_spec_is_named_tuple(self):
        s = AliasSpec(make="anthropic", model="claude-opus-4-5")
        assert s == ("anthropic", "claude-opus-4-5")

    def test_spec_model_can_be_none(self):
        assert AliasSpec(make="xai", model=None).model is None


class TestLoadAliases:
    def test_missing_file_yields_empty_registry(self, alias_file):
        assert not alias_file.exists()
        reload_aliases()
        assert dict(get_aliases()) == {}
        assert get_alias_load_error() is None

    def test_blank_file_yields_empty_registry(self, alias_file):
        alias_file.write_text("   \n  ")
        reload_aliases()
        assert dict(get_aliases()) == {}
        assert get_alias_load_error() is None

    def test_v1_happy_path(self, alias_file):
        _write_v1(alias_file, {
            "anthropic-opus":   {"make": "anthropic", "model": "claude-opus-4-5"},
            "anthropic-sonnet": {"make": "anthropic", "model": "claude-sonnet-4-5"},
        })
        reload_aliases()
        assert list(get_aliases().keys()) == ["anthropic-opus", "anthropic-sonnet"]
        assert get_aliases()["anthropic-opus"] == AliasSpec("anthropic", "claude-opus-4-5")
        assert get_alias_load_error() is None

    def test_v2_happy_path(self, alias_file):
        _write_v2(alias_file, {
            "opus":   {"provider": "anthropic", "model": "claude-opus-4-5"},
            "sonnet": {"provider": "anthropic", "model": "claude-sonnet-4-5"},
        })
        reload_aliases()
        assert list(get_aliases().keys()) == ["opus", "sonnet"]
        assert get_aliases()["opus"] == AliasSpec("anthropic", "claude-opus-4-5")
        assert get_alias_load_error() is None

    def test_malformed_json_recorded_as_error(self, alias_file):
        alias_file.write_text("{not valid json")
        reload_aliases()
        assert dict(get_aliases()) == {}
        assert "Could not read" in (get_alias_load_error() or "")

    def test_unknown_provider_rejected(self, alias_file):
        _write_v1(alias_file, {"weird": {"make": "no_such_provider", "model": "x"}})
        reload_aliases()
        assert "weird" not in get_aliases()
        assert "unknown provider" in (get_alias_load_error() or "").lower()

    def test_top_level_not_object_rejected(self, alias_file):
        alias_file.write_text(json.dumps(["not", "a", "dict"]))
        reload_aliases()
        assert dict(get_aliases()) == {}
        assert "must be a JSON object" in (get_alias_load_error() or "")

    def test_v2_provider_wins_when_both_keys_present(self, alias_file):
        envelope = {
            "version": 2,
            "agents": {"mixed": {"provider": "anthropic", "make": "openai", "model": "x"}},
            "_migrated_to_agents_v2": True,
        }
        alias_file.write_text(json.dumps(envelope))
        reload_aliases()
        assert get_aliases()["mixed"].make == "anthropic"


class TestResolveAlias:
    def test_user_agent_resolves(self, alias_file):
        _write_v2(alias_file, {"opus": {"provider": "anthropic", "model": "claude-opus-4-5"}})
        reload_aliases()
        assert resolve_alias("opus") == AliasSpec("anthropic", "claude-opus-4-5")

    def test_unknown_with_empty_registry_hints_setup(self, alias_file):
        with pytest.raises(ValueError) as exc:
            resolve_alias("anthropic")
        msg = str(exc.value)
        assert "Unsupported AI model" in msg
        assert "No agents defined" in msg
        assert "st-admin --setup" in msg

    def test_unknown_with_defined_agents_suggests_typo(self, alias_file):
        _write_v2(alias_file, {"anthropic": {"provider": "anthropic", "model": None}})
        reload_aliases()
        with pytest.raises(ValueError, match="Did you mean 'anthropic'"):
            resolve_alias("antrhopic")

    def test_unknown_no_close_match_no_suggestion(self, alias_file):
        _write_v2(alias_file, {"opus": {"provider": "anthropic", "model": "x"}})
        reload_aliases()
        with pytest.raises(ValueError) as exc:
            resolve_alias("zzzzzz")
        assert "Did you mean" not in str(exc.value)

    def test_no_late_registered_make_fallback(self, alias_file, monkeypatch):
        monkeypatch.setitem(AI_HANDLER_REGISTRY, "experimental", MagicMock())
        try:
            with pytest.raises(ValueError):
                resolve_alias("experimental")
        finally:
            AI_HANDLER_REGISTRY.pop("experimental", None)


class TestDidYouMean:
    def test_close_match(self):
        assert did_you_mean("anthorpic", ["anthropic", "openai", "xai"]) == "anthropic"

    def test_no_close_match(self):
        assert did_you_mean("zzzzzz", ["anthropic", "openai"]) is None

    def test_exact_match_returned(self):
        assert did_you_mean("openai", ["openai", "xai"]) == "openai"

    def test_empty_candidates(self):
        assert did_you_mean("anything", []) is None


class TestMigrateV1ToV2:
    def test_v1_flat_dict_becomes_envelope(self):
        v2 = migrate_v1_to_v2({
            "opus": {"make": "anthropic", "model": "claude-opus-4-5"},
            "mini": {"make": "openai",    "model": "gpt-4o-mini"},
        })
        assert v2["version"] == SCHEMA_VERSION
        assert v2["_migrated_to_agents_v2"] is True
        assert v2["agents"]["opus"] == {"provider": "anthropic", "model": "claude-opus-4-5"}
        assert v2["agents"]["mini"] == {"provider": "openai",    "model": "gpt-4o-mini"}

    def test_idempotent_on_v2_input(self):
        v2_in = {
            "version": 2,
            "agents": {"opus": {"provider": "anthropic", "model": "x"}},
            "_migrated_to_agents_v2": True,
        }
        v2_out = migrate_v1_to_v2(v2_in)
        assert v2_out["version"] == 2
        assert v2_out["agents"]["opus"]["provider"] == "anthropic"
        assert v2_out["_migrated_to_agents_v2"] is True

    def test_marker_forced_true_even_when_missing_on_v2_input(self):
        assert migrate_v1_to_v2({"version": 2, "agents": {}})["_migrated_to_agents_v2"] is True

    def test_skips_non_dict_inner_values(self):
        v2 = migrate_v1_to_v2({"good": {"make": "anthropic", "model": "x"}, "bad": "junk"})
        assert "good" in v2["agents"] and "bad" not in v2["agents"]

    def test_skips_inner_specs_missing_provider(self):
        assert migrate_v1_to_v2({"orphan": {"model": "x"}})["agents"] == {}


class TestWriteAgentsFile:
    def test_round_trip(self, alias_file):
        write_agents_file(
            {"opus": AliasSpec("anthropic", "claude-opus-4-5"),
             "mini": AliasSpec("openai", "gpt-4o-mini")},
            str(alias_file),
        )
        reload_aliases()
        assert get_aliases()["opus"] == AliasSpec("anthropic", "claude-opus-4-5")
        assert get_aliases()["mini"] == AliasSpec("openai", "gpt-4o-mini")

    def test_emits_v2_envelope_with_provider_inner_key(self, alias_file):
        write_agents_file({"opus": AliasSpec("anthropic", "x")}, str(alias_file))
        on_disk = json.loads(alias_file.read_text())
        assert on_disk["version"] == 2
        assert on_disk["_migrated_to_agents_v2"] is True
        assert on_disk["agents"]["opus"] == {"provider": "anthropic", "model": "x"}

    def test_preserves_iteration_order(self, alias_file):
        from collections import OrderedDict
        agents = OrderedDict([
            ("z-last",  AliasSpec("anthropic", "x")),
            ("a-first", AliasSpec("openai",    "y")),
        ])
        write_agents_file(agents, str(alias_file))
        on_disk = json.loads(alias_file.read_text())
        assert list(on_disk["agents"].keys()) == ["z-last", "a-first"]

    def test_atomic_no_partial_file_on_failure(self, alias_file, monkeypatch):
        good = {
            "version": 2,
            "agents": {"keep": {"provider": "openai", "model": "x"}},
            "_migrated_to_agents_v2": True,
        }
        alias_file.write_text(json.dumps(good))

        def boom(*a, **kw):
            raise RuntimeError("disk full")

        monkeypatch.setattr(json, "dump", boom)
        with pytest.raises(RuntimeError):
            write_agents_file({"new": AliasSpec("openai", "y")}, str(alias_file))
        assert json.loads(alias_file.read_text()) == good


class TestKeysModule:
    def test_provider_env_var_map_covers_all_built_ins(self):
        for make in AI_LIST:
            assert make in PROVIDER_API_KEY_ENV
            assert isinstance(PROVIDER_API_KEY_ENV[make], tuple)
            assert len(PROVIDER_API_KEY_ENV[make]) >= 1

    def test_has_api_key_true_when_set(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert has_api_key("anthropic") is True

    def test_has_api_key_false_when_unset(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert has_api_key("anthropic") is False

    def test_has_api_key_false_when_blank(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "   ")
        assert has_api_key("openai") is False

    def test_has_api_key_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            has_api_key("not_a_provider")

    def test_has_api_key_gemini_accepts_either_env_name(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "g-test")
        assert has_api_key("gemini") is True
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "g-test-2")
        assert has_api_key("gemini") is True

    def test_api_key_env_var_returns_canonical_name(self):
        assert api_key_env_var("anthropic") == "ANTHROPIC_API_KEY"
        assert api_key_env_var("gemini") == "GEMINI_API_KEY"

    def test_api_key_env_var_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            api_key_env_var("not_a_provider")


class TestRateLimitGroup:
    def test_two_agents_same_provider_share_group(self, alias_file):
        _write_v2(alias_file, {
            "opus":   {"provider": "anthropic", "model": "claude-opus-4-5"},
            "sonnet": {"provider": "anthropic", "model": "claude-sonnet-4-5"},
        })
        reload_aliases()
        g1, c1 = get_rate_limit_group("opus")
        g2, c2 = get_rate_limit_group("sonnet")
        assert g1 == g2 == "anthropic"
        assert c1 == c2 == 2

    def test_unknown_alias_raises(self, alias_file):
        with pytest.raises(ValueError):
            get_rate_limit_group("no-such-agent")


@pytest.fixture
def mock_handler(monkeypatch):
    handler = MagicMock()
    handler.get_payload.return_value = {"model": "mock-default"}
    handler.get_model.return_value = "mock-default"
    handler.get_cached_response.return_value = ({"text": "ok"}, False)
    monkeypatch.setitem(AI_HANDLER_REGISTRY, "mock_make", handler)
    yield handler
    AI_HANDLER_REGISTRY.pop("mock_make", None)


class TestProcessPromptAliasAware:
    def test_unknown_alias_raises_in_empty_registry(self, alias_file, mock_handler):
        with pytest.raises(ValueError):
            process_prompt("mock_make", "hi", use_cache=False)

    def test_self_alias_resolves(self, alias_file, mock_handler):
        _write_v2(alias_file, {"mock_make": {"provider": "mock_make", "model": None}})
        reload_aliases()
        result = process_prompt("mock_make", "hi", use_cache=False)
        assert result.response["_make"] == "mock_make"
        assert result.response["_alias"] == "mock_make"
        assert result.response["_model"] == "mock-default"

    def test_alias_resolves_to_make_and_model(self, alias_file, mock_handler):
        _write_v2(alias_file, {"mock-fast": {"provider": "mock_make", "model": "mock-fast-v1"}})
        reload_aliases()
        result = process_prompt("mock-fast", "hi", use_cache=False)
        assert result.response["_make"] == "mock_make"
        assert result.response["_alias"] == "mock-fast"
        assert result.response["_model"] == "mock-fast-v1"
        assert result.model == "mock-fast-v1"

    def test_explicit_model_kwarg_wins(self, alias_file, mock_handler):
        _write_v2(alias_file, {"mock-fast": {"provider": "mock_make", "model": "mock-fast-v1"}})
        reload_aliases()
        result = process_prompt("mock-fast", "hi", use_cache=False, model="overridden")
        assert result.response["_model"] == "overridden"

    def test_alias_env_var_overrides_spec(self, alias_file, mock_handler, monkeypatch):
        _write_v2(alias_file, {"mock-fast": {"provider": "mock_make", "model": "mock-fast-v1"}})
        reload_aliases()
        monkeypatch.setenv("MOCK_FAST_MODEL", "from-alias-env")
        result = process_prompt("mock-fast", "hi", use_cache=False)
        assert result.response["_model"] == "from-alias-env"

    def test_make_env_var_legacy_fallback(self, alias_file, mock_handler, monkeypatch):
        _write_v2(alias_file, {"mock_make": {"provider": "mock_make", "model": None}})
        reload_aliases()
        monkeypatch.setenv("MOCK_MAKE_MODEL", "from-make-env")
        result = process_prompt("mock_make", "hi", use_cache=False)
        assert result.response["_model"] == "from-make-env"


class TestAliasesShareClient:
    def test_two_aliases_same_make_share_client(self, alias_file, monkeypatch):
        construction_count = [0]
        sentinel_client = object()
        handler = MagicMock()
        handler.get_payload.return_value = {"model": "x"}
        handler.get_model.return_value = "x"
        handler.get_cached_response.side_effect = lambda *a, **kw: (
            (kw["client_factory"]() and {"text": "ok"}, False)
        )

        def _make_client():
            construction_count[0] += 1
            return sentinel_client

        handler.get_client.side_effect = _make_client
        monkeypatch.setitem(AI_HANDLER_REGISTRY, "mock_share", handler)
        try:
            _write_v2(alias_file, {
                "share-a": {"provider": "mock_share", "model": "a"},
                "share-b": {"provider": "mock_share", "model": "b"},
            })
            reload_aliases()
            process_prompt("share-a", "hi", use_cache=False)
            process_prompt("share-b", "hi", use_cache=False)
            assert construction_count[0] == 1
            assert _client_cache.get("mock_share") is sentinel_client
        finally:
            AI_HANDLER_REGISTRY.pop("mock_share", None)


class TestListAndDefault:
    def test_get_ai_list_returns_agents(self, alias_file):
        _write_v2(alias_file, {"opus": {"provider": "anthropic", "model": "claude-opus-4-5"}})
        reload_aliases()
        assert "opus" in get_ai_list()

    def test_get_ai_list_empty_when_no_agents(self, alias_file):
        assert get_ai_list() == []

    def test_get_default_ai_accepts_default_agent_env(self, alias_file, monkeypatch):
        _write_v2(alias_file, {"opus": {"provider": "anthropic", "model": "x"}})
        reload_aliases()
        monkeypatch.setenv("DEFAULT_AGENT", "opus")
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        assert get_default_ai() == "opus"

    def test_get_default_ai_falls_back_to_legacy_default_ai(self, alias_file, monkeypatch):
        _write_v2(alias_file, {"opus": {"provider": "anthropic", "model": "x"}})
        reload_aliases()
        monkeypatch.delenv("DEFAULT_AGENT", raising=False)
        monkeypatch.setenv("DEFAULT_AI", "opus")
        assert get_default_ai() == "opus"

    def test_get_default_ai_returns_first_agent_when_no_env(self, alias_file, monkeypatch):
        _write_v2(alias_file, {
            "first":  {"provider": "openai",    "model": "gpt-4o"},
            "second": {"provider": "anthropic", "model": "claude-opus-4-5"},
        })
        reload_aliases()
        monkeypatch.delenv("DEFAULT_AGENT", raising=False)
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        assert get_default_ai() == "first"

    def test_get_default_ai_returns_none_when_empty(self, alias_file, monkeypatch):
        monkeypatch.delenv("DEFAULT_AGENT", raising=False)
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        assert get_default_ai() is None

    def test_get_ai_make_returns_resolved_make(self, alias_file):
        _write_v2(alias_file, {"opus": {"provider": "anthropic", "model": "x"}})
        reload_aliases()
        assert get_ai_make("opus") == "anthropic"

    def test_get_ai_model_alias_resolution(self, alias_file):
        _write_v2(alias_file, {"opus": {"provider": "anthropic", "model": "claude-opus-4-5"}})
        reload_aliases()
        assert get_ai_model("opus") == "claude-opus-4-5"


class TestPublicExports:
    def test_exports_include_new_agent_names(self):
        for name in (
            "AliasSpec", "resolve_alias", "get_aliases",
            "get_alias_load_error", "did_you_mean", "get_rate_limit_group",
            "reload_aliases", "get_ai_make_list",
            "get_agents",
            "has_api_key", "api_key_env_var", "PROVIDER_API_KEY_ENV",
            "migrate_v1_to_v2", "write_agents_file",
        ):
            assert hasattr(cross_ai_core, name), f"{name} not exported"

    def test_get_agents_is_alias_of_get_aliases(self):
        assert get_agents() is get_aliases()

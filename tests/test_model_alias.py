import importlib.util


SCRIPT = (
    __file__.replace("/tests/test_model_alias.py", "/.agents/skills/"
    "code-agent-control/scripts/code_agent_control.py")
)
SPEC = importlib.util.spec_from_file_location("code_agent_control", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_resolves_provider_model_id_to_registered_alias(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        '[models."kimi-code/kimi-for-coding"]\n'
        'provider = "managed:kimi-code"\n'
        'model = "kimi-for-coding"\n'
        '\n'
        '[models."kimi-code/k3"]\n'
        'provider = "managed:kimi-code"\n'
        'model = "k3"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path))

    assert MODULE.kimi_model_aliases() == [
        ("kimi-code/kimi-for-coding", "kimi-for-coding"),
        ("kimi-code/k3", "k3"),
    ]
    assert MODULE.resolve_kimi_model("kimi-for-coding") == "kimi-code/kimi-for-coding"
    assert MODULE.resolve_kimi_model("kimi-code/kimi-for-coding") == "kimi-code/kimi-for-coding"


def test_unknown_model_fails_before_dispatch(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        '[models."kimi-code/k3"]\nmodel = "k3"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path))

    try:
        MODULE.resolve_kimi_model("not-registered")
    except ValueError as exc:
        assert "not-registered" in str(exc)
        assert "kimi-code/k3" in str(exc)
    else:
        raise AssertionError("unknown model should fail")

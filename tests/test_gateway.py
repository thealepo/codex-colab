from __future__ import annotations

import json

import pytest

from codex_colab.gateway import (
    DEFAULT_UPSTREAM_SPEC,
    GatewayError,
    RemoteResult,
    UpstreamConfig,
)


def test_default_upstream_is_official_and_release_pinned(monkeypatch) -> None:
    monkeypatch.delenv("CODEX_COLAB_UPSTREAM_COMMAND", raising=False)
    monkeypatch.delenv("CODEX_COLAB_UPSTREAM_ARGS_JSON", raising=False)
    monkeypatch.delenv("CODEX_COLAB_UPSTREAM_SPEC", raising=False)

    config = UpstreamConfig.from_environment()

    assert config.command == "uvx"
    assert config.args == (DEFAULT_UPSTREAM_SPEC,)
    assert "github.com/googlecolab/colab-mcp" in config.args[0]
    assert config.args[0].endswith("@v1.0.2")


def test_upstream_process_can_be_overridden_without_a_shell(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_COLAB_UPSTREAM_COMMAND", "python3")
    monkeypatch.setenv(
        "CODEX_COLAB_UPSTREAM_ARGS_JSON", json.dumps(["-m", "fake_colab_server"])
    )

    config = UpstreamConfig.from_environment()

    assert config.command == "python3"
    assert config.args == ("-m", "fake_colab_server")


def test_invalid_upstream_arguments_are_rejected(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_COLAB_UPSTREAM_ARGS_JSON", '{"not":"an array"}')

    with pytest.raises(GatewayError, match="JSON string array"):
        UpstreamConfig.from_environment()


def test_remote_result_omits_absent_structured_content() -> None:
    result = RemoteResult(content=({"type": "text", "text": "ok"},))

    assert result.as_dict() == {
        "content": [{"type": "text", "text": "ok"}],
        "is_error": False,
    }

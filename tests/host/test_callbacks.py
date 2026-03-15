from __future__ import annotations

from pathlib import Path

import requests

from host.pipeline import PipelineConfig, PipelineResult, send_status_callback


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _config() -> PipelineConfig:
    return PipelineConfig(
        repository_path=Path("."),
        codex_cmd=["echo", "unused"],
        codex_prompt_template=Path("prompts/commit_message_prompt.txt"),
        diff_max_chars=1000,
        commit_timeout_seconds=10,
        push_timeout_seconds=10,
        callback_url="http://localhost:5001/status/commit",
        callback_token="token-1",
        callback_timeout_seconds=0.1,
        callback_retries=2,
        callback_backoff_seconds=0.0,
    )


def test_send_status_callback_retries_until_success(monkeypatch) -> None:
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        if len(calls) < 3:
            return _Response(500)
        return _Response(200)

    monkeypatch.setattr("host.pipeline.requests.post", fake_post)

    send_status_callback(
        _config(),
        PipelineResult(success=True, status="success", request_id="r1"),
    )

    assert len(calls) == 3
    assert calls[0][1]["Authorization"] == "Bearer token-1"


def test_send_status_callback_handles_request_exception(monkeypatch) -> None:
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        raise requests.RequestException("boom")

    monkeypatch.setattr("host.pipeline.requests.post", fake_post)

    send_status_callback(
        _config(),
        PipelineResult(success=False, status="failed", request_id="r2", error="x"),
    )

    assert len(calls) == 3

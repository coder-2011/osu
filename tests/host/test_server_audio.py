from __future__ import annotations

from host.pipeline import PipelineResult
from host.server import create_app


class _FakeAudio:
    def __init__(self) -> None:
        self.notify = 0
        self.success = 0
        self.error = 0
        self.test_tones: list[tuple[int | None, int | None]] = []

    def play_notify(self) -> None:
        self.notify += 1

    def play_success(self) -> None:
        self.success += 1

    def play_error(self) -> None:
        self.error += 1

    def play_test_tone(self, frequency_hz: int | None = None, duration_ms: int | None = None) -> None:
        self.test_tones.append((frequency_hz, duration_ms))


def test_notify_endpoint_plays_local_audio(monkeypatch) -> None:
    fake = _FakeAudio()
    monkeypatch.setattr("host.server.LocalAudioPlayer", lambda: fake)
    monkeypatch.setenv("OSU_NOTIFY_TOKEN", "tok")

    app = create_app()
    client = app.test_client()

    unauthorized = client.post("/notify/codex", json={"event_type": "agent-turn-complete"})
    assert unauthorized.status_code == 401

    authorized = client.post(
        "/notify/codex",
        headers={"Authorization": "Bearer tok"},
        json={"event_type": "agent-turn-complete"},
    )
    assert authorized.status_code == 202
    assert fake.notify == 1


def test_button_press_plays_start_and_completion_audio(monkeypatch) -> None:
    class ImmediateThread:
        def __init__(self, target, kwargs, name, daemon) -> None:
            self._target = target
            self._kwargs = kwargs

        def start(self) -> None:
            self._target(**self._kwargs)

    fake = _FakeAudio()
    monkeypatch.setattr("host.server.LocalAudioPlayer", lambda: fake)
    monkeypatch.setattr("host.server.threading.Thread", ImmediateThread)
    monkeypatch.setattr(
        "host.server.run_pipeline",
        lambda _cfg, request_id: PipelineResult(success=True, status="success", request_id=request_id),
    )
    monkeypatch.setattr("host.server.send_status_callback", lambda _cfg, _result: None)

    app = create_app()
    client = app.test_client()

    response = client.post("/button/press")

    assert response.status_code == 202
    assert fake.notify == 1
    assert fake.success == 1
    assert fake.error == 0


def test_audio_test_endpoint_plays_test_tone(monkeypatch) -> None:
    fake = _FakeAudio()
    monkeypatch.setattr("host.server.LocalAudioPlayer", lambda: fake)
    monkeypatch.setenv("OSU_HOST_TOKEN", "host-token")

    app = create_app()
    client = app.test_client()

    unauthorized = client.post("/audio/test", json={"frequency_hz": 660, "duration_ms": 120})
    assert unauthorized.status_code == 401

    authorized = client.post(
        "/audio/test",
        headers={"Authorization": "Bearer host-token"},
        json={"frequency_hz": 660, "duration_ms": 120},
    )
    assert authorized.status_code == 202
    assert fake.test_tones == [(660, 120)]

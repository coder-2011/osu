from __future__ import annotations

from host.server import create_app


class _FakeAudio:
    def __init__(self) -> None:
        self.notify = 0
        self.success = 0
        self.error = 0

    def play_notify(self) -> None:
        self.notify += 1

    def play_success(self) -> None:
        self.success += 1

    def play_error(self) -> None:
        self.error += 1


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

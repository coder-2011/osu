from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List

from pi.server import PiConfig, create_app


@dataclass
class FakeHardware:
    events: List[str] = field(default_factory=list)
    button_callback: Callable[[], None] | None = None

    def set_idle(self) -> None:
        self.events.append("set_idle")

    def set_pending(self) -> None:
        self.events.append("set_pending")

    def set_working(self) -> None:
        self.events.append("set_working")

    def indicate_notify(self) -> None:
        self.events.append("indicate_notify")

    def indicate_success(self) -> None:
        self.events.append("indicate_success")

    def indicate_error(self) -> None:
        self.events.append("indicate_error")

    def set_button_callback(self, callback: Callable[[], None]) -> None:
        self.events.append("set_button_callback")
        self.button_callback = callback


def _config() -> PiConfig:
    return PiConfig(
        host_button_url="http://localhost:5000/button/press",
        host_notify_url="http://localhost:5000/notify/codex",
        host_token="host-token",
        host_notify_token="notify-token",
        callback_token="pi-token",
        host_timeout_seconds=0.1,
        host_retries=0,
        host_backoff_seconds=0.0,
        notify_min_interval_ms=0,
        dedupe_bucket_ms=500,
        dedupe_ring_size=16,
    )


def test_healthz() -> None:
    hardware = FakeHardware()
    app = create_app(config=_config(), hardware=hardware)
    client = app.test_client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert "set_button_callback" in hardware.events


def test_notify_requires_auth() -> None:
    app = create_app(config=_config(), hardware=FakeHardware())
    client = app.test_client()

    response = client.post("/notify/codex", json={"event_type": "agent-turn-complete"})

    assert response.status_code == 401


def test_notify_dedupes_same_bucket() -> None:
    hardware = FakeHardware()
    app = create_app(config=_config(), hardware=hardware)
    client = app.test_client()
    headers = {"Authorization": "Bearer pi-token"}

    first = client.post(
        "/notify/codex",
        headers=headers,
        json={"event_type": "agent-turn-complete", "thread_id": "t1"},
    )
    second = client.post(
        "/notify/codex",
        headers=headers,
        json={"event_type": "agent-turn-complete", "thread_id": "t1"},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert hardware.events.count("indicate_notify") == 1


def test_notify_forwards_to_host_for_local_audio(monkeypatch) -> None:
    calls = []

    class Response:
        status_code = 202

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return Response()

    monkeypatch.setattr("pi.server.requests.post", fake_post)

    hardware = FakeHardware()
    app = create_app(config=_config(), hardware=hardware)
    client = app.test_client()

    response = client.post(
        "/notify/codex",
        headers={"Authorization": "Bearer pi-token"},
        json={"event_type": "agent-turn-complete", "thread_id": "t1"},
    )

    assert response.status_code == 202
    assert calls[0][0] == "http://localhost:5000/notify/codex"
    assert calls[0][1]["Authorization"] == "Bearer notify-token"


def test_status_commit_success_updates_hardware() -> None:
    hardware = FakeHardware()
    app = create_app(config=_config(), hardware=hardware)
    client = app.test_client()

    response = client.post(
        "/status/commit",
        headers={"Authorization": "Bearer pi-token"},
        json={"success": True},
    )

    assert response.status_code == 200
    assert response.get_json()["state"] == "success"
    assert hardware.events == ["set_button_callback", "indicate_success", "set_idle"]


def test_status_commit_failure_updates_hardware() -> None:
    hardware = FakeHardware()
    app = create_app(config=_config(), hardware=hardware)
    client = app.test_client()

    response = client.post(
        "/status/commit",
        headers={"Authorization": "Bearer pi-token"},
        json={"success": False},
    )

    assert response.status_code == 200
    assert response.get_json()["state"] == "error"
    assert hardware.events == ["set_button_callback", "indicate_error"]


def test_button_press_forwards_to_host(monkeypatch) -> None:
    class Response:
        status_code = 202

    def fake_post(*args, **kwargs):
        return Response()

    monkeypatch.setattr("pi.server.requests.post", fake_post)

    hardware = FakeHardware()
    app = create_app(config=_config(), hardware=hardware)
    client = app.test_client()

    response = client.post("/button/press")

    assert response.status_code == 202
    assert response.get_json() == {"forwarded": True}
    assert hardware.events == ["set_button_callback", "set_pending", "set_working"]


def test_button_press_failure_sets_error(monkeypatch) -> None:
    class Response:
        status_code = 500

    def fake_post(*args, **kwargs):
        return Response()

    monkeypatch.setattr("pi.server.requests.post", fake_post)

    hardware = FakeHardware()
    app = create_app(config=_config(), hardware=hardware)
    client = app.test_client()

    response = client.post("/button/press")

    assert response.status_code == 502
    assert response.get_json() == {"forwarded": False}
    assert hardware.events == ["set_button_callback", "set_pending", "indicate_error"]


def test_hardware_button_callback_forwards(monkeypatch) -> None:
    class Response:
        status_code = 202

    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr("pi.server.requests.post", fake_post)

    hardware = FakeHardware()
    create_app(config=_config(), hardware=hardware)
    assert hardware.button_callback is not None

    hardware.button_callback()

    assert len(calls) == 1
    assert hardware.events[-2:] == ["set_pending", "set_working"]

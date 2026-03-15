from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests
from flask import Flask, jsonify, request

from pi.hardware import HardwareController, build_default_hardware


@dataclass(frozen=True)
class PiConfig:
    host_button_url: str
    host_token: str | None
    callback_token: str | None
    host_timeout_seconds: float
    host_retries: int
    host_backoff_seconds: float
    notify_min_interval_ms: int
    dedupe_bucket_ms: int
    dedupe_ring_size: int


class NotifyDeduper:
    def __init__(self, bucket_ms: int, ring_size: int, min_interval_ms: int) -> None:
        self._bucket_ms = bucket_ms
        self._seen_order: deque[tuple[tuple[str, str], int]] = deque(maxlen=ring_size)
        self._seen_latest: dict[tuple[str, str], int] = {}
        self._ring_size = ring_size
        self._min_interval_ms = min_interval_ms
        self._last_notify_ms = 0

    def should_accept(self, event_type: str, thread_id: str | None) -> bool:
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_notify_ms < self._min_interval_ms:
            return False

        key = (event_type, thread_id or "")
        last_seen = self._seen_latest.get(key)
        if last_seen is not None and now_ms - last_seen < self._bucket_ms:
            return False

        self._seen_latest[key] = now_ms
        self._seen_order.append((key, now_ms))
        self._purge_expired(now_ms)
        self._last_notify_ms = now_ms
        return True

    def _purge_expired(self, now_ms: int) -> None:
        while self._seen_order:
            key, timestamp_ms = self._seen_order[0]
            too_old = now_ms - timestamp_ms >= self._bucket_ms
            over_capacity = len(self._seen_order) > self._ring_size
            if not too_old and not over_capacity:
                break

            self._seen_order.popleft()
            latest = self._seen_latest.get(key)
            if latest == timestamp_ms:
                self._seen_latest.pop(key, None)


def load_config() -> PiConfig:
    return PiConfig(
        host_button_url=os.getenv("OSU_HOST_BUTTON_URL", "http://localhost:5000/button/press"),
        host_token=os.getenv("OSU_HOST_TOKEN"),
        callback_token=os.getenv("OSU_PI_TOKEN"),
        host_timeout_seconds=float(os.getenv("OSU_HOST_TIMEOUT_SECONDS", "2.0")),
        host_retries=int(os.getenv("OSU_HOST_RETRIES", "2")),
        host_backoff_seconds=float(os.getenv("OSU_HOST_BACKOFF_SECONDS", "0.2")),
        notify_min_interval_ms=int(os.getenv("OSU_NOTIFY_MIN_INTERVAL_MS", "250")),
        dedupe_bucket_ms=int(os.getenv("OSU_NOTIFY_DEDUPE_BUCKET_MS", "1000")),
        dedupe_ring_size=int(os.getenv("OSU_NOTIFY_DEDUPE_RING_SIZE", "512")),
    )


def create_app(
    config: PiConfig | None = None,
    hardware: HardwareController | None = None,
) -> Flask:
    app = Flask(__name__)
    cfg = config or load_config()

    logger = app.logger
    hw = hardware or build_default_hardware(logger)
    deduper = NotifyDeduper(
        bucket_ms=cfg.dedupe_bucket_ms,
        ring_size=cfg.dedupe_ring_size,
        min_interval_ms=cfg.notify_min_interval_ms,
    )
    lock = threading.Lock()

    def log_event(event: str, **fields: Any) -> None:
        payload = {
            "event": event,
            "timestamp": datetime.now(UTC).isoformat(),
            **fields,
        }
        logger.info(json.dumps(payload, sort_keys=True))

    def require_auth() -> bool:
        if not cfg.callback_token:
            return True

        header = request.headers.get("Authorization", "")
        return header == f"Bearer {cfg.callback_token}"

    @app.get("/healthz")
    def healthz() -> Any:
        return jsonify({"ok": True})

    @app.post("/button/press")
    def button_press() -> Any:
        with lock:
            hw.set_pending()

        payload = {
            "source": "osu-pi",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        headers = {"Content-Type": "application/json"}
        if cfg.host_token:
            headers["Authorization"] = f"Bearer {cfg.host_token}"

        for attempt in range(cfg.host_retries + 1):
            try:
                response = requests.post(
                    cfg.host_button_url,
                    headers=headers,
                    json=payload,
                    timeout=cfg.host_timeout_seconds,
                )
                if 200 <= response.status_code < 300:
                    with lock:
                        hw.set_working()
                    log_event("button.forwarded", status=response.status_code)
                    return jsonify({"forwarded": True}), 202

                if attempt == cfg.host_retries:
                    with lock:
                        hw.indicate_error()
                    log_event("button.forward_failed", status=response.status_code)
                    return jsonify({"forwarded": False}), 502
            except requests.RequestException:
                if attempt == cfg.host_retries:
                    with lock:
                        hw.indicate_error()
                    log_event("button.forward_failed", reason="request_exception")
                    return jsonify({"forwarded": False}), 502

                time.sleep(cfg.host_backoff_seconds)

        with lock:
            hw.indicate_error()
        return jsonify({"forwarded": False}), 502

    @app.post("/notify/codex")
    def notify_codex() -> Any:
        if not require_auth():
            return jsonify({"error": "unauthorized"}), 401

        payload = request.get_json(silent=True) or {}
        event_type = str(payload.get("event_type") or "unknown")
        thread_id = payload.get("thread_id")

        with lock:
            accepted = deduper.should_accept(event_type=event_type, thread_id=thread_id)
            if accepted:
                hw.indicate_notify()

        if not accepted:
            log_event("notify.ignored", reason="debounced", event_type=event_type)
            return jsonify({"accepted": False, "reason": "debounced"}), 202

        log_event("notify.accepted", event_type=event_type)
        return jsonify({"accepted": True}), 202

    @app.post("/status/commit")
    def status_commit() -> Any:
        if not require_auth():
            return jsonify({"error": "unauthorized"}), 401

        payload = request.get_json(silent=True) or {}
        success = bool(payload.get("success"))

        with lock:
            if success:
                hw.indicate_success()
                hw.set_idle()
                state = "success"
            else:
                hw.indicate_error()
                state = "error"

        log_event("status.received", success=success)
        return jsonify({"ok": True, "state": state}), 200

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5001)

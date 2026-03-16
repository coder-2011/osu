from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from flask import Flask, jsonify, request

from host.audio import LocalAudioPlayer
from host.pipeline import PipelineConfig, load_pipeline_config, run_pipeline, send_status_callback


def create_app(config: PipelineConfig | None = None) -> Flask:
    app = Flask(__name__)
    app.config["OSU_PIPELINE_CONFIG"] = config or load_pipeline_config()
    host_token = os.getenv("OSU_HOST_TOKEN")
    notify_token = os.getenv("OSU_NOTIFY_TOKEN")
    audio = LocalAudioPlayer()

    logger = logging.getLogger("osu-host")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    pipeline_lock = threading.Lock()

    def _log(event: str, **fields: Any) -> None:
        record = {
            "event": event,
            "timestamp": datetime.now(UTC).isoformat(),
            **fields,
        }
        logger.info(json.dumps(record, sort_keys=True))

    def _run_and_callback(request_id: str) -> None:
        cfg: PipelineConfig = app.config["OSU_PIPELINE_CONFIG"]
        try:
            result = run_pipeline(cfg, request_id=request_id)
            if result.success:
                audio.play_success()
            else:
                audio.play_error()
            _log(
                "pipeline.completed",
                request_id=request_id,
                success=result.success,
                status=result.status,
                commit_sha=result.commit_sha,
            )
            send_status_callback(cfg, result)
        finally:
            pipeline_lock.release()

    @app.get("/healthz")
    def healthz() -> Any:
        return jsonify({"ok": True})

    @app.post("/button/press")
    @app.post("/commit")
    def button_press() -> Any:
        if host_token:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {host_token}":
                return jsonify({"error": "unauthorized"}), 401

        request_id = str(uuid.uuid4())

        if not pipeline_lock.acquire(blocking=False):
            _log("pipeline.rejected", request_id=request_id, reason="pipeline_busy")
            return jsonify({"accepted": False, "reason": "pipeline_busy"}), 409

        _log("pipeline.accepted", request_id=request_id)
        audio.play_notify()

        thread = threading.Thread(
            target=_run_and_callback,
            kwargs={"request_id": request_id},
            name=f"pipeline-{request_id[:8]}",
            daemon=True,
        )
        thread.start()

        return jsonify({"accepted": True, "request_id": request_id}), 202

    @app.post("/notify/codex")
    def notify_codex() -> Any:
        if notify_token:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {notify_token}":
                return jsonify({"error": "unauthorized"}), 401

        audio.play_notify()
        return jsonify({"accepted": True}), 202

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000)

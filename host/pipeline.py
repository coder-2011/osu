from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests


@dataclass(frozen=True)
class PipelineConfig:
    repository_path: Path
    codex_cmd: list[str]
    codex_prompt_template: Path
    diff_max_chars: int
    commit_timeout_seconds: int
    push_timeout_seconds: int
    callback_url: str
    callback_token: str | None
    callback_timeout_seconds: float
    callback_retries: int
    callback_backoff_seconds: float


@dataclass(frozen=True)
class PipelineResult:
    success: bool
    status: str
    request_id: str
    commit_message: str | None = None
    commit_sha: str | None = None
    error: str | None = None


class PipelineError(RuntimeError):
    """Raised for expected pipeline failures."""


def load_pipeline_config() -> PipelineConfig:
    return PipelineConfig(
        repository_path=Path(os.getenv("OSU_REPO_PATH", os.getcwd())).resolve(),
        codex_cmd=shlex.split(os.getenv("OSU_CODEX_CMD", "codex exec")),
        codex_prompt_template=Path(
            os.getenv(
                "OSU_PROMPT_TEMPLATE",
                "prompts/commit_message_prompt.txt",
            )
        ).resolve(),
        diff_max_chars=int(os.getenv("OSU_DIFF_MAX_CHARS", "12000")),
        commit_timeout_seconds=int(os.getenv("OSU_COMMIT_TIMEOUT_SECONDS", "180")),
        push_timeout_seconds=int(os.getenv("OSU_PUSH_TIMEOUT_SECONDS", "180")),
        callback_url=os.getenv(
            "OSU_PI_STATUS_URL",
            "http://osu-pi.local:5001/status/commit",
        ),
        callback_token=os.getenv("OSU_PI_TOKEN"),
        callback_timeout_seconds=float(os.getenv("OSU_CALLBACK_TIMEOUT_SECONDS", "2.0")),
        callback_retries=int(os.getenv("OSU_CALLBACK_RETRIES", "2")),
        callback_backoff_seconds=float(os.getenv("OSU_CALLBACK_BACKOFF_SECONDS", "0.2")),
    )


def run_pipeline(config: PipelineConfig, request_id: str | None = None) -> PipelineResult:
    request_id = request_id or str(uuid.uuid4())

    try:
        _run_git(config, ["add", "-A"])

        diff = _run_git(config, ["diff", "--cached", "--no-ext-diff", "--", "."])
        if not diff.strip():
            return PipelineResult(
                success=False,
                status="no_changes",
                request_id=request_id,
                error="No staged changes to commit.",
            )

        commit_message = _generate_commit_message(config, diff)
        _run_git(
            config,
            ["commit", "-m", commit_message],
            timeout_seconds=config.commit_timeout_seconds,
        )
        commit_sha = _run_git(config, ["rev-parse", "HEAD"]).strip()
        _run_git(
            config,
            ["push", "origin", "HEAD"],
            timeout_seconds=config.push_timeout_seconds,
        )

        return PipelineResult(
            success=True,
            status="success",
            request_id=request_id,
            commit_message=commit_message,
            commit_sha=commit_sha,
        )
    except PipelineError as err:
        return PipelineResult(
            success=False,
            status="failed",
            request_id=request_id,
            error=str(err),
        )


def send_status_callback(config: PipelineConfig, result: PipelineResult) -> None:
    payload: dict[str, Any] = {
        "request_id": result.request_id,
        "success": result.success,
        "status": result.status,
        "commit_message": result.commit_message,
        "commit_sha": result.commit_sha,
        "error": result.error,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    headers = {"Content-Type": "application/json"}
    if config.callback_token:
        headers["Authorization"] = f"Bearer {config.callback_token}"

    for attempt in range(config.callback_retries + 1):
        try:
            response = requests.post(
                config.callback_url,
                headers=headers,
                json=payload,
                timeout=config.callback_timeout_seconds,
            )
            if 200 <= response.status_code < 300:
                return
            if attempt == config.callback_retries:
                return
            time.sleep(config.callback_backoff_seconds)
        except requests.RequestException:
            if attempt == config.callback_retries:
                return
            time.sleep(config.callback_backoff_seconds)


def _generate_commit_message(config: PipelineConfig, diff: str) -> str:
    diff_excerpt = diff[: config.diff_max_chars]
    prompt_template = _read_prompt_template(config.codex_prompt_template)
    prompt = prompt_template.replace("{{DIFF}}", diff_excerpt)

    raw = _run_command(
        config,
        config.codex_cmd,
        input_text=prompt,
        timeout_seconds=config.commit_timeout_seconds,
        error_prefix="Codex invocation failed",
    )

    line = first_commit_line(raw)
    if not line:
        raise PipelineError("Codex returned an empty commit message")

    return sanitize_commit_message(line)


def _read_prompt_template(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as err:
        raise PipelineError(f"Unable to read prompt template at {path}: {err}") from err


def _run_git(
    config: PipelineConfig,
    args: list[str],
    timeout_seconds: int = 60,
) -> str:
    return _run_command(
        config,
        ["git", *args],
        timeout_seconds=timeout_seconds,
        error_prefix=f"git {' '.join(args)} failed",
    )


def _run_command(
    config: PipelineConfig,
    command: list[str],
    input_text: str | None = None,
    timeout_seconds: int = 60,
    error_prefix: str = "Command failed",
) -> str:
    try:
        proc = subprocess.run(
            command,
            cwd=config.repository_path,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except OSError as err:
        raise PipelineError(f"{error_prefix}: {err}") from err
    except subprocess.TimeoutExpired as err:
        raise PipelineError(f"{error_prefix}: timed out after {timeout_seconds}s") from err

    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "(no stderr)"
        raise PipelineError(f"{error_prefix}: {stderr}")

    return proc.stdout


def first_commit_line(raw: str) -> str:
    for line in raw.splitlines():
        candidate = line.strip()
        if candidate:
            return candidate
    return ""


def sanitize_commit_message(message: str) -> str:
    cleaned = message.strip().strip('"').strip("'")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > 72:
        cleaned = cleaned[:72].rstrip()

    if not cleaned:
        raise PipelineError("Commit message was empty after sanitization")

    if cleaned.endswith("."):
        cleaned = cleaned[:-1]

    return cleaned


def result_to_json(result: PipelineResult) -> str:
    return json.dumps(
        {
            "success": result.success,
            "status": result.status,
            "request_id": result.request_id,
            "commit_message": result.commit_message,
            "commit_sha": result.commit_sha,
            "error": result.error,
        }
    )

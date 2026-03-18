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
    commit_strategy: str
    codex_prompt_template: Path
    project_context_file: Path | None
    project_context_max_chars: int
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
    commit_hashes: list[str] | None = None
    commit_messages: list[str] | None = None
    error: str | None = None


class PipelineError(RuntimeError):
    """Raised for expected pipeline failures."""


def load_pipeline_config() -> PipelineConfig:
    project_context_file = os.getenv("OSU_PROJECT_CONTEXT_FILE", "prompts/project_context.txt").strip()
    commit_strategy = os.getenv("OSU_COMMIT_STRATEGY", "single").strip().lower()
    default_prompt = (
        "prompts/agent_commit_session_prompt.txt"
        if commit_strategy == "agent_multi"
        else "prompts/commit_message_prompt.txt"
    )
    return PipelineConfig(
        repository_path=Path(os.getenv("OSU_REPO_PATH", os.getcwd())).resolve(),
        codex_cmd=shlex.split(os.getenv("OSU_CODEX_CMD", "codex exec")),
        commit_strategy=commit_strategy,
        codex_prompt_template=Path(
            os.getenv(
                "OSU_PROMPT_TEMPLATE",
                default_prompt,
            )
        ).resolve(),
        project_context_file=Path(project_context_file).resolve() if project_context_file else None,
        project_context_max_chars=int(os.getenv("OSU_PROJECT_CONTEXT_MAX_CHARS", "4000")),
        diff_max_chars=int(os.getenv("OSU_DIFF_MAX_CHARS", "12000")),
        commit_timeout_seconds=int(os.getenv("OSU_COMMIT_TIMEOUT_SECONDS", "180")),
        push_timeout_seconds=int(os.getenv("OSU_PUSH_TIMEOUT_SECONDS", "180")),
        callback_url=os.getenv(
            "OSU_PI_STATUS_URL",
            "",
        ),
        callback_token=os.getenv("OSU_PI_TOKEN"),
        callback_timeout_seconds=float(os.getenv("OSU_CALLBACK_TIMEOUT_SECONDS", "2.0")),
        callback_retries=int(os.getenv("OSU_CALLBACK_RETRIES", "2")),
        callback_backoff_seconds=float(os.getenv("OSU_CALLBACK_BACKOFF_SECONDS", "0.2")),
    )


def run_pipeline(config: PipelineConfig, request_id: str | None = None) -> PipelineResult:
    request_id = request_id or str(uuid.uuid4())

    try:
        branch = _run_git(config, ["branch", "--show-current"]).strip()
        status_short = _run_git(config, ["status", "--short"])
        if not status_short.strip():
            return PipelineResult(
                success=False,
                status="no_changes",
                request_id=request_id,
                error="No local changes to commit.",
            )

        before_sha = _run_git(config, ["rev-parse", "HEAD"]).strip()

        if config.commit_strategy == "agent_multi":
            _run_agent_commit_session(config, branch, status_short)
            head_after_agent = _run_git(config, ["rev-parse", "HEAD"]).strip()
            if head_after_agent == before_sha:
                _run_fallback_agent_commit(config)
        else:
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

        after_sha = _run_git(config, ["rev-parse", "HEAD"]).strip()
        commit_hashes, commit_messages = _collect_commit_range(config, before_sha, after_sha)
        if not commit_hashes:
            raise PipelineError("No commits were created.")

        current_branch = _run_git(config, ["branch", "--show-current"]).strip()
        if current_branch != branch:
            raise PipelineError("Branch changed during commit session; refusing to push.")

        _run_git(
            config,
            ["push", "origin", "HEAD"],
            timeout_seconds=config.push_timeout_seconds,
        )

        return PipelineResult(
            success=True,
            status="success",
            request_id=request_id,
            commit_message=commit_messages[-1],
            commit_sha=commit_hashes[-1],
            commit_hashes=commit_hashes,
            commit_messages=commit_messages,
        )
    except PipelineError as err:
        return PipelineResult(
            success=False,
            status="failed",
            request_id=request_id,
            error=str(err),
        )


def send_status_callback(config: PipelineConfig, result: PipelineResult) -> None:
    if not config.callback_url.strip():
        return

    payload: dict[str, Any] = {
        "request_id": result.request_id,
        "success": result.success,
        "status": result.status,
        "commit_message": result.commit_message,
        "commit_sha": result.commit_sha,
        "commit_hashes": result.commit_hashes,
        "commit_messages": result.commit_messages,
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
    project_context = _read_project_context(config)
    prompt = _build_prompt(prompt_template, diff_excerpt, project_context)

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


def _run_agent_commit_session(config: PipelineConfig, branch: str, status_short: str) -> None:
    project_context = _read_project_context(config)
    prompt_template = _read_prompt_template(config.codex_prompt_template)
    diff_unstaged = _run_git(config, ["diff", "--no-ext-diff", "--", "."])
    diff_cached = _run_git(config, ["diff", "--cached", "--no-ext-diff", "--", "."])
    diff_stat = _run_git(config, ["diff", "--stat"])

    prompt = (
        prompt_template.replace("{{PROJECT_CONTEXT}}", project_context or "(none provided)")
        .replace("{{BRANCH}}", branch)
        .replace("{{STATUS_SHORT}}", status_short)
        .replace("{{DIFF_UNSTAGED}}", diff_unstaged)
        .replace("{{DIFF_CACHED}}", diff_cached)
        .replace("{{DIFF_STAT}}", diff_stat)
    )

    _run_command(
        config,
        config.codex_cmd,
        input_text=prompt,
        timeout_seconds=max(config.commit_timeout_seconds, 300),
        error_prefix="Codex agent commit session failed",
    )


def _run_fallback_agent_commit(config: PipelineConfig) -> None:
    _run_git(config, ["add", "-A"])
    diff = _run_git(config, ["diff", "--cached", "--no-ext-diff", "--", "."])
    if not diff.strip():
        raise PipelineError("No commits were created.")

    default_message = os.getenv(
        "OSU_AGENT_FALLBACK_COMMIT_MESSAGE",
        "chore: apply pending workspace changes",
    )
    commit_message = sanitize_commit_message(default_message)
    _run_git(
        config,
        ["commit", "-m", commit_message],
        timeout_seconds=config.commit_timeout_seconds,
    )


def _read_prompt_template(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as err:
        raise PipelineError(f"Unable to read prompt template at {path}: {err}") from err


def _read_project_context(config: PipelineConfig) -> str:
    if not config.project_context_file:
        return ""

    try:
        text = config.project_context_file.read_text(encoding="utf-8")
    except OSError:
        return ""

    return text[: config.project_context_max_chars].strip()


def _build_prompt(prompt_template: str, diff_excerpt: str, project_context: str) -> str:
    prompt = prompt_template.replace("{{DIFF}}", diff_excerpt)
    if "{{PROJECT_CONTEXT}}" in prompt:
        return prompt.replace("{{PROJECT_CONTEXT}}", project_context or "(none provided)")

    if not project_context:
        return prompt

    return (
        "Project context:\n"
        f"{project_context}\n\n"
        f"{prompt}"
    )


def _collect_commit_range(config: PipelineConfig, before_sha: str, after_sha: str) -> tuple[list[str], list[str]]:
    if before_sha == after_sha:
        return [], []

    raw = _run_git(
        config,
        ["log", "--reverse", "--format=%H%x1f%s", f"{before_sha}..{after_sha}"],
    ).strip()
    if not raw:
        return [], []

    hashes: list[str] = []
    messages: list[str] = []
    for line in raw.splitlines():
        if "\x1f" in line:
            commit_hash, message = line.split("\x1f", 1)
        else:
            commit_hash, message = line, ""
        hashes.append(commit_hash.strip())
        messages.append(message.strip())

    return hashes, messages


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
    env = _command_env(command)

    try:
        proc = subprocess.run(
            command,
            cwd=config.repository_path,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=env,
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


def _command_env(command: list[str]) -> dict[str, str]:
    env = os.environ.copy()
    if command and command[0] == "git":
        # Always fail fast instead of opening interactive auth prompts.
        env.setdefault("GIT_TERMINAL_PROMPT", "0")
        env.setdefault("GIT_ASKPASS", "/bin/false")
        env.setdefault("SSH_ASKPASS", "/bin/false")
        env.setdefault("GCM_INTERACTIVE", "Never")
    return env


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
            "commit_hashes": result.commit_hashes,
            "commit_messages": result.commit_messages,
            "error": result.error,
        }
    )

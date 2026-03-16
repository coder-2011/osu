from __future__ import annotations

import os
import subprocess
from pathlib import Path

from host.pipeline import PipelineConfig, run_pipeline


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    _run(["git", "init"], path)
    _run(["git", "config", "user.email", "osu@example.com"], path)
    _run(["git", "config", "user.name", "Osu Bot"], path)
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    _run(["git", "add", "-A"], path)
    _run(["git", "commit", "-m", "chore: seed"], path)


def test_run_pipeline_success_with_stub_codex(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    # Bare remote so push origin HEAD succeeds locally.
    remote = tmp_path / "remote.git"
    _run(["git", "init", "--bare", str(remote)], tmp_path)
    _run(["git", "remote", "add", "origin", str(remote)], repo)

    (repo / "feature.txt").write_text("value\n", encoding="utf-8")

    codex_stub = tmp_path / "codex_stub.sh"
    codex_stub.write_text("#!/bin/sh\necho 'feat: add feature file'\n", encoding="utf-8")
    os.chmod(codex_stub, 0o755)

    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Commit:\n{{DIFF}}\n", encoding="utf-8")

    cfg = PipelineConfig(
        repository_path=repo,
        codex_cmd=[str(codex_stub)],
        commit_strategy="single",
        codex_prompt_template=prompt,
        project_context_file=None,
        project_context_max_chars=1000,
        diff_max_chars=4000,
        commit_timeout_seconds=30,
        push_timeout_seconds=30,
        callback_url="http://localhost:9/unused",
        callback_token=None,
        callback_timeout_seconds=0.2,
        callback_retries=0,
        callback_backoff_seconds=0.0,
    )

    result = run_pipeline(cfg, request_id="req-1")

    assert result.success is True
    assert result.status == "success"
    assert result.commit_message == "feat: add feature file"
    assert result.commit_sha


def test_run_pipeline_no_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Commit:\n{{DIFF}}\n", encoding="utf-8")

    cfg = PipelineConfig(
        repository_path=repo,
        codex_cmd=["sh", "-c", "echo 'fix: x'"],
        commit_strategy="single",
        codex_prompt_template=prompt,
        project_context_file=None,
        project_context_max_chars=1000,
        diff_max_chars=4000,
        commit_timeout_seconds=30,
        push_timeout_seconds=30,
        callback_url="http://localhost:9/unused",
        callback_token=None,
        callback_timeout_seconds=0.2,
        callback_retries=0,
        callback_backoff_seconds=0.0,
    )

    result = run_pipeline(cfg, request_id="req-2")

    assert result.success is False
    assert result.status == "no_changes"
    assert "No local changes" in (result.error or "")


def test_run_pipeline_agent_multi_groups_multiple_commits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    remote = tmp_path / "remote.git"
    _run(["git", "init", "--bare", str(remote)], tmp_path)
    _run(["git", "remote", "add", "origin", str(remote)], repo)

    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    (repo / "b.txt").write_text("b\n", encoding="utf-8")

    codex_stub = tmp_path / "codex_multi_stub.sh"
    codex_stub.write_text(
        "#!/bin/sh\n"
        "git add a.txt\n"
        "git commit -m 'feat: add topic a'\n"
        "git add b.txt\n"
        "git commit -m 'fix: add topic b'\n",
        encoding="utf-8",
    )
    os.chmod(codex_stub, 0o755)

    prompt = tmp_path / "prompt_agent.txt"
    prompt.write_text(
        "Branch: {{BRANCH}}\\nStatus:\\n{{STATUS_SHORT}}\\nDiff:\\n{{DIFF_UNSTAGED}}\\n",
        encoding="utf-8",
    )

    cfg = PipelineConfig(
        repository_path=repo,
        codex_cmd=[str(codex_stub)],
        commit_strategy="agent_multi",
        codex_prompt_template=prompt,
        project_context_file=None,
        project_context_max_chars=1000,
        diff_max_chars=4000,
        commit_timeout_seconds=30,
        push_timeout_seconds=30,
        callback_url="http://localhost:9/unused",
        callback_token=None,
        callback_timeout_seconds=0.2,
        callback_retries=0,
        callback_backoff_seconds=0.0,
    )

    result = run_pipeline(cfg, request_id="req-3")

    assert result.success is True
    assert result.status == "success"
    assert result.commit_hashes is not None
    assert result.commit_messages is not None
    assert len(result.commit_hashes) == 2
    assert result.commit_messages == ["feat: add topic a", "fix: add topic b"]

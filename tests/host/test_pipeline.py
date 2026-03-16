from host.pipeline import (
    PipelineError,
    _build_prompt,
    _command_env,
    first_commit_line,
    sanitize_commit_message,
)


def test_first_commit_line_uses_first_non_empty_line() -> None:
    raw = "\n\nfeat: add host route\nextra details"
    assert first_commit_line(raw) == "feat: add host route"


def test_sanitize_commit_message_trims_quotes_and_period() -> None:
    result = sanitize_commit_message('"fix: update retry policy."')
    assert result == "fix: update retry policy"


def test_sanitize_commit_message_enforces_limit() -> None:
    result = sanitize_commit_message("feat: " + "a" * 120)
    assert len(result) <= 72


def test_sanitize_commit_message_rejects_empty() -> None:
    try:
        sanitize_commit_message("   ")
    except PipelineError as err:
        assert "empty" in str(err).lower()
    else:
        raise AssertionError("Expected PipelineError")


def test_build_prompt_injects_project_context_placeholder() -> None:
    template = "Context:\\n{{PROJECT_CONTEXT}}\\n\\nDiff:\\n{{DIFF}}\\n"
    prompt = _build_prompt(template, "diff-content", "project-notes")
    assert "project-notes" in prompt
    assert "diff-content" in prompt


def test_build_prompt_prepends_context_if_placeholder_missing() -> None:
    template = "Diff only:\\n{{DIFF}}\\n"
    prompt = _build_prompt(template, "diff-content", "project-notes")
    assert prompt.startswith("Project context:")
    assert "project-notes" in prompt


def test_command_env_for_git_disables_interactive_prompts() -> None:
    env = _command_env(["git", "push", "origin", "HEAD"])
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == "/bin/false"
    assert env["SSH_ASKPASS"] == "/bin/false"
    assert env["GCM_INTERACTIVE"] == "Never"

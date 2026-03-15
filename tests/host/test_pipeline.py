from host.pipeline import PipelineError, first_commit_line, sanitize_commit_message


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

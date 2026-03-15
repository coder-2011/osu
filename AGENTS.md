# Repository Guidelines

## Project Structure & Module Organization
Osu is a split system: a thin AIY Voice Kit on Raspberry Pi (button, LED, speaker) and a host computer running all logic.

- `pi/`: Flask service that receives status callbacks and controls LED/chime hardware
- `host/`: Flask service and commit pipeline (`git add/commit/push`, Codex prompt handoff)
- `hooks/`: Codex notify-hook integration (Rust `codex-notify-chime` modifications)
- `prompts/`: repo-specific prompt templates passed to `codex exec`
- `tests/`: unit/integration tests by subsystem (`tests/pi`, `tests/host`, `tests/hooks`)

Keep hardware I/O code isolated from git/agent logic. The Pi should remain stateless and "dumb."

## Build, Test, and Development Commands
Use one command per workflow and keep local loop fast.

- `just dev-pi` or `python -m flask --app pi.server run --port 5001`: run Pi service locally
- `just dev-host` or `python -m flask --app host.server run --port 5000`: run host service locally
- `just test` or `pytest -q`: run full test suite
- `just lint` or `ruff check . && black --check .`: static checks and formatting
- `cargo test -p codex-notify-chime`: test notify-hook binary changes

## Coding Style & Naming Conventions
Python: 4-space indentation, type hints on public functions, `snake_case` modules/functions, `PascalCase` classes.  
Rust: `rustfmt` defaults; keep network payload structs explicit and versioned.  
Use concise endpoint names (`/button/press`, `/notify/done`) and typed request/response schemas.

## Testing Guidelines
Required coverage areas:

- Button press lifecycle (yellow -> host run -> green/error)
- Host pipeline steps (stage, diff, prompt, commit, push)
- Callback reliability (idempotent POST retries, timeout handling)
- Notify-hook fan-out when multiple Codex instances finish

Name tests by behavior, e.g., `test_button_press_starts_commit_pipeline`.

## Commit & Pull Request Guidelines
Use Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`). Keep subject lines imperative and scoped.

PRs must include:

- What changed in Pi vs host paths
- Test evidence (`pytest`, `cargo test`, manual hardware check notes)
- Any prompt or hook contract changes

## Security & Configuration Tips
Do not commit secrets or machine-local paths. Store API keys and host addresses in `.env.local`, and maintain `.env.example` with placeholder values only.

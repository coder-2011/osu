# Osu

Local-first workflow tool where a Pi button triggers a host-side commit pipeline, and Codex notify events are routed to Pi audio/LED callbacks.

## Prerequisites

- Python 3.11+ on host and Pi
- Git configured in the target repository
- Codex CLI installed on host (`codex` command)
- Shared bearer token configured for Pi callback endpoints

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env.local
```

## Run Services

Host service (computer):

```bash
source .venv/bin/activate
python -m flask --app host.server run --host 0.0.0.0 --port 5000
```

Pi service:

```bash
source .venv/bin/activate
python -m flask --app pi.server run --host 0.0.0.0 --port 5001
```

## Tests

```bash
source .venv/bin/activate
pytest -q
```

## Notify Adapter (Rust)

```bash
cd codex-notify-chime
cargo test
cargo run -- --test
```

Configure Codex CLI globally:

```toml
# ~/.codex/config.toml
notify = ["codex-notify-chime"]
```

## Service Manifests

- Host launchd: `deploy/launchd/com.osu.host.plist`
- Pi systemd: `deploy/systemd/osu-pi.service`

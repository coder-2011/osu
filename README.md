# Osu

Local-first workflow tool where a Pi button triggers a host-side commit pipeline, while audio alerts play on the host machine and Pi is used for button + LED state.

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

Commit-message context file:
- Edit `prompts/project_context.txt` with stable project/domain guidance.
- Set `OSU_PROJECT_CONTEXT_FILE` to point to a different `.txt` file if needed.
- Set `OSU_PROJECT_CONTEXT_MAX_CHARS` to cap injected context size.
- Set `OSU_COMMIT_STRATEGY=agent_multi` to let Codex create multiple scoped commits.
- Use `OSU_PROMPT_TEMPLATE=prompts/agent_commit_session_prompt.txt` for the multi-commit agent mode.

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

## Local Machine Audio (WAV)

Audio now runs on the host machine by default:
- commit/push success -> local `success.wav`
- commit/push failure -> local `error.wav`
- Codex notify callback -> local `notify.wav`

Configure:
- `OSU_LOCAL_AUDIO_ENABLED=1`
- `OSU_LOCAL_SOUND_BASE_DIR` or explicit `OSU_LOCAL_SOUND_*_WAV` paths
- optional `OSU_LOCAL_AUDIO_PLAYER` (`afplay`, `aplay`, or `ffplay`)

Pi is treated as button + LED only. No audio is played on Pi.
Pi `/notify/codex` forwards accepted notify events to host `/notify/codex` so the sound plays locally.
If your Pi hostname is default, use `pi.local` in callback URLs (for example `OSU_PI_STATUS_URL=http://pi.local:5001/status/commit`).

## Quick GPIO Button Test (Pi CLI)

Run this directly on the Raspberry Pi to verify raw button presses:

```bash
python -m pi.button_gpio_test --pin 23
```

Press the AIY button and you should see `button_press ...` lines in the terminal.
Use `Ctrl+C` to stop. If your wiring differs, set another BCM pin via `--pin`.

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

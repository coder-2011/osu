# Osu

Local-first workflow tool where a Pi button triggers a host-side commit pipeline, while audio alerts play on the host machine and Pi is used for button + LED state.

Pi hardware integration is GPIO-only (`RPi.GPIO`) with no `aiy` dependency.

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
python -m host.server
```

Pi service:

```bash
python3 -m pi.server
```

## Local Machine Audio (WAV)

Audio now runs on the host machine by default:
- button press accepted -> local `notify.wav` (start cue)
- commit/push success -> local `success.wav` (done cue)
- commit/push failure -> local `error.wav` (done cue)
- Codex notify callback -> local `notify.wav`

Configure:
- `OSU_LOCAL_AUDIO_ENABLED=1`
- `OSU_LOCAL_SOUND_BASE_DIR` or explicit `OSU_LOCAL_SOUND_*_WAV` paths
- optional `OSU_LOCAL_AUDIO_PLAYER` (`afplay`, `aplay`, or `ffplay`)

Pi is treated as button + LED only. No audio is played on Pi.
Pi `/notify/codex` forwards accepted notify events to host `/notify/codex` so the sound plays locally.
If your Pi hostname is default, use `pi.local` in callback URLs (for example `OSU_PI_STATUS_URL=http://pi.local:5001/status/commit`).
Pi LED behavior:
- idle-ready: constant orange
- button acknowledged: green
- host pipeline running: green pulse
- success/error: terminal success or error indicator, then return to idle
To suppress duplicate
hardware callbacks from button press/release transitions, tune `OSU_BUTTON_MIN_INTERVAL_MS`
(`1000` default).

## Quick GPIO Button Test (Pi CLI)

Run this directly on the Raspberry Pi to verify raw button presses:

```bash
python -m pi.button_gpio_test --pin 23
```

Press the GPIO-wired button and you should see `button_press ...` lines in the terminal.
Use `Ctrl+C` to stop. If your wiring differs, set another BCM pin via `--pin`.
The script also lights the configured GPIO LED pin green while running (disable with `--no-led-green`).

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

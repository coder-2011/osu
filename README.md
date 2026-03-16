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

## Speaker Done Signal (Pi)

To guarantee a sound when commit/push completes:
1. Put WAV files on Pi:
   - `/home/pi/sounds/notify.wav`
   - `/home/pi/sounds/success.wav`
   - `/home/pi/sounds/error.wav`
2. Set sound env vars (`OSU_SOUND_*`) if you use different paths.
3. Keep `OSU_PI_STATUS_URL` on host pointed to Pi `/status/commit`.

On success callback, Pi runs `indicate_success()` then returns LED to idle.
If AIY audio helper is unavailable, playback falls back to `aplay`.

## Local Machine Audio (WAV)

Audio now runs on the host machine by default:
- commit/push success -> local `success.wav`
- commit/push failure -> local `error.wav`
- Codex notify callback -> local `notify.wav`

Configure:
- `OSU_LOCAL_AUDIO_ENABLED=1`
- `OSU_LOCAL_SOUND_BASE_DIR` or explicit `OSU_LOCAL_SOUND_*_WAV` paths
- optional `OSU_LOCAL_AUDIO_PLAYER` (`afplay`, `aplay`, or `ffplay`)

`codex-notify-chime` default callback URL is `http://localhost:5000/notify/codex`.
Pi audio is disabled by default (`OSU_PI_AUDIO_ENABLED=0`).

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

# Osu Technical Implementation Plan

## 1. Objective
Implement Osu as an always-on local system where:

1. The AIY button triggers a host-side commit pipeline.
2. Codex notify events from any local repo are routed to the AIY speaker/LED.
3. No per-session SSH or manual startup is required.

This plan standardizes on a **global notify hook** plus per-machine service daemons.

## 2. Final Architecture
### 2.1 Components
- **Pi Service (`osu-pi`)**: Flask API + AIY hardware control (button input, LED state, speaker output).
- **Host Service (`osu-host`)**: Flask API + git/Codex commit pipeline orchestration.
- **Notify Adapter (`codex-notify-chime`)**: Rust binary used by Codex `notify` hook; sends event callbacks to Pi instead of local speaker.

### 2.2 Responsibility Split
- Pi performs only I/O and simple state transitions.
- Host performs compute, git operations, Codex invocation, retry logic, and monitoring decisions.
- Notify adapter is stateless transport/format logic.

## 3. Global Notify Strategy
### 3.1 Codex Global Hook
Set once in `~/.codex/config.toml`:

```toml
notify = ["codex-notify-chime"]
```

Codex invokes this binary with one JSON argument per notify event.

### 3.2 Adapter Behavior
Current `codex-notify-chime` plays local audio. Replace default path with:

1. Parse notification JSON argument.
2. POST normalized payload to Pi endpoint (`/notify/codex`).
3. Exit successfully even if callback fails (non-blocking for Codex workflow).

Local speaker playback becomes an optional fallback mode for debugging.

## 4. Notify Adapter Technical Spec
### 4.1 Config (Environment Variables)
- `OSU_NOTIFY_MODE=http|audio` (default: `http`)
- `OSU_NOTIFY_URL` (e.g., `http://osu-pi.local:5001/notify/codex`)
- `OSU_NOTIFY_TOKEN` (shared secret)
- `OSU_NOTIFY_TIMEOUT_MS` (default 800)
- `OSU_NOTIFY_RETRIES` (default 2)
- `OSU_NOTIFY_BACKOFF_MS` (default 150)

### 4.2 Request Contract
`POST /notify/codex`

Headers:
- `Authorization: Bearer <OSU_NOTIFY_TOKEN>`
- `Content-Type: application/json`

Body:
```json
{
  "source": "codex-notify-chime",
  "event_type": "agent-turn-complete",
  "thread_id": "optional",
  "last_assistant_message": "optional",
  "input_messages": ["optional"],
  "hostname": "host-machine",
  "pid": 12345,
  "timestamp": "2026-03-15T22:00:00Z"
}
```

### 4.3 Exit Semantics
- Invalid CLI payload JSON: exit `1` (real invocation error).
- HTTP failure/timeouts: log warning, exit `0`.
- Unknown event type: still POST and exit `0`.

## 5. Pi Service API and Behavior
### 5.1 Endpoints
- `POST /button/press` (internal hardware trigger path)
- `POST /notify/codex` (notify adapter callback)
- `POST /status/commit` (host pipeline completion callback)
- `GET /healthz`

### 5.2 Audio/LED Rules
- Notify callback: short chime only; no persistent LED change.
- Commit pipeline start: LED yellow.
- Commit success: LED green + success chime.
- Commit failure: LED red + error tone pattern.

### 5.3 Rate Control
- Debounce notify chimes with configurable minimum interval (e.g., 250 ms).
- Keep a recent-event ring buffer keyed by `(event_type, thread_id, timestamp_bucket)` to reduce accidental duplicates.

## 6. Always-On Service Management
### 6.1 Pi Boot Service (systemd)
- Unit name: `osu-pi.service`
- `Restart=always`
- `WantedBy=multi-user.target`
- Starts automatically on boot; no SSH required.

### 6.2 Host Login Service (launchd)
- Label: `com.osu.host`
- `RunAtLoad=true`
- `KeepAlive=true`
- Writes logs to `~/Library/Logs/osu-host.log`.

Result: first button press and first Codex event work without manual startup.

## 7. Networking and Discovery
- Prefer mDNS hostname (`osu-pi.local`) over hardcoded IP.
- Keep services on local WiFi only.
- If mDNS is unstable, add host fallback list: `OSU_NOTIFY_URLS` with ordered retry.

## 8. Security Model
- Require bearer token on Pi callback endpoints.
- Reject unauthenticated requests with `401`.
- Optional allowlist by host subnet or specific host IP.
- Never log full secrets; redact token values.

## 9. Observability
- Structured JSON logs on both Pi and host with correlation ID (`request_id`).
- Metrics counters:
  - `notify_events_total`
  - `notify_post_failures_total`
  - `pi_chime_played_total`
  - `button_press_total`
  - `commit_pipeline_success_total` / `commit_pipeline_failure_total`

## 10. Rollout Plan
1. Modify `codex-notify-chime` for HTTP mode and fallback audio mode.
2. Implement `POST /notify/codex` on Pi with auth + chime action.
3. Add systemd/launchd service manifests.
4. Configure global Codex notify hook.
5. Validate with:
   - `cargo run -- --test`
   - synthetic notify payload POST
   - real Codex turn completion from two concurrent sessions.
6. Run 48-hour soak test for reliability and duplicate/noise tuning.

## 11. Open Decisions (Defaults Proposed)
- Event filtering: chime all events by default, optional filter list later.
- Failure behavior: callback failure is non-fatal to Codex (`exit 0`).
- Burst policy: allow all events initially, then tune debounce threshold from real usage.

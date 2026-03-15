# Osu Project Plan

## Vision
Build a desk-native workflow tool where a physical button triggers high-quality AI-assisted git commits, and a shared notification channel reports Codex agent progress in real time.

Osu means "push": a physical push button and a git push workflow unified in one system.

## Product Definition
Osu consists of two connected capabilities:

1. Commit Button: one-press commit and push using Codex-generated commit messages.
2. Agent Monitor: completion alerts for many parallel Codex sessions.

## Core Principles
- AIY kit is thin I/O only (button, LED, speaker).
- Host computer runs all logic (git, prompts, Codex, monitoring).
- Local network communication via two small Flask services.
- No extra cloud product beyond existing Codex usage.

## System Architecture
### Raspberry Pi (AIY Voice Kit)
- Detects button press.
- Sends POST to host computer.
- Receives completion status callback.
- Plays chime and updates LED state.

### Host Computer
- Runs commit pipeline and agent notification handling.
- Stages changes, computes diff, and invokes `codex exec` with a repo-specific prompt.
- Creates commit, pushes to GitHub, reports status back to Pi.

## Workflow: Commit Button
1. User presses physical button.
2. Pi sets LED yellow and POSTs event to host.
3. Host executes pipeline: stage -> diff -> Codex commit message -> commit -> push.
4. Host POSTs result back to Pi.
5. Pi plays chime and sets LED green on success (or error state on failure).

## Workflow: Agent Monitor
1. Each Codex instance emits a native notify-hook event on turn completion.
2. Modified `codex-notify-chime` (Rust) sends POST to Pi instead of local audio output.
3. Pi plays chime to signal completed agent work.

## Prompting Strategy
- Use a purpose-built project prompt for commit message generation.
- Do not rely on generic `AGENTS.md` behavior for commit-message intent.
- Prompt must include project context and diff semantics.

## Implementation Milestones
1. Stand up Pi Flask endpoint for button input and status output.
2. Stand up host Flask endpoint for commit pipeline trigger.
3. Implement robust host git/Codex pipeline with clear failure states.
4. Integrate callback contract and LED/chime state mapping.
5. Modify and wire `codex-notify-chime` to POST to Pi.
6. Validate end-to-end with multiple concurrent Codex sessions.

## Reliability and Safety Requirements
- Idempotent callback handling.
- Timeouts and retries for inter-device POST calls.
- Explicit failure reporting (LED/audio pattern + logs).
- No blocking UI dependency; system must work from editor-first workflow.
- Keep Pi logic minimal; avoid moving compute from host to Pi.

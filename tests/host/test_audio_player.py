from __future__ import annotations

from pathlib import Path

from host.audio import LocalAudioPlayer


def test_play_test_tone_invokes_player_and_cleans_temp_wav(monkeypatch) -> None:
    calls: list[list[str]] = []

    class _Proc:
        returncode = 0

    def fake_run(command, check, capture_output, text, timeout):  # type: ignore[no-untyped-def]
        calls.append(command)
        assert Path(command[1]).exists()
        return _Proc()

    monkeypatch.setenv("OSU_LOCAL_AUDIO_ENABLED", "1")
    monkeypatch.setenv("OSU_LOCAL_AUDIO_PLAYER", "/usr/bin/fake-player")
    monkeypatch.setattr("host.audio.subprocess.run", fake_run)

    player = LocalAudioPlayer()
    player.play_test_tone(frequency_hz=990, duration_ms=140)

    assert len(calls) == 1
    played_path = Path(calls[0][1])
    assert not played_path.exists()


def test_play_test_tone_is_noop_when_audio_disabled(monkeypatch) -> None:
    called = {"run": 0}

    def fake_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        called["run"] += 1

    monkeypatch.setenv("OSU_LOCAL_AUDIO_ENABLED", "0")
    monkeypatch.setenv("OSU_LOCAL_AUDIO_PLAYER", "/usr/bin/fake-player")
    monkeypatch.setattr("host.audio.subprocess.run", fake_run)

    player = LocalAudioPlayer()
    player.play_test_tone()

    assert called["run"] == 0


def test_notify_sound_defaults_to_bundled_chime_asset(monkeypatch) -> None:
    monkeypatch.setenv("OSU_LOCAL_AUDIO_ENABLED", "1")
    monkeypatch.setenv("OSU_LOCAL_AUDIO_PLAYER", "/usr/bin/fake-player")
    monkeypatch.delenv("OSU_LOCAL_SOUND_NOTIFY_WAV", raising=False)
    monkeypatch.delenv("OSU_LOCAL_SOUND_BASE_DIR", raising=False)

    player = LocalAudioPlayer()

    assert player.notify_wav is not None
    assert player.notify_wav.endswith("codex-notify-chime/assets/notify.mp3")


def test_play_notify_falls_back_to_test_tone_when_sound_missing(monkeypatch) -> None:
    calls: list[tuple[int | None, int | None]] = []

    monkeypatch.setenv("OSU_LOCAL_AUDIO_ENABLED", "1")
    monkeypatch.setenv("OSU_LOCAL_AUDIO_PLAYER", "/usr/bin/fake-player")
    player = LocalAudioPlayer()
    monkeypatch.setattr(player, "_play", lambda _path: False)
    monkeypatch.setattr(
        player,
        "play_test_tone",
        lambda frequency_hz=None, duration_ms=None: calls.append((frequency_hz, duration_ms)),
    )

    player.play_notify()

    assert calls == [(1046, 140)]


def test_notify_prefers_macos_glass_when_afplay_available(monkeypatch) -> None:
    monkeypatch.setenv("OSU_LOCAL_AUDIO_ENABLED", "1")
    monkeypatch.setenv("OSU_LOCAL_AUDIO_PLAYER", "/usr/bin/afplay")
    monkeypatch.delenv("OSU_LOCAL_SOUND_NOTIFY_WAV", raising=False)
    monkeypatch.delenv("OSU_LOCAL_SOUND_BASE_DIR", raising=False)

    def fake_exists(path: Path) -> bool:
        return str(path) == "/System/Library/Sounds/Glass.aiff"

    monkeypatch.setattr("host.audio.Path.exists", fake_exists)

    player = LocalAudioPlayer()

    assert player.notify_wav == "/System/Library/Sounds/Glass.aiff"


def test_play_agent_done_uses_shell_command(monkeypatch) -> None:
    calls: list[list[str]] = []

    class _Proc:
        returncode = 0

    def fake_run(command, check, capture_output, text, timeout):  # type: ignore[no-untyped-def]
        calls.append(command)
        return _Proc()

    monkeypatch.setenv("OSU_LOCAL_AUDIO_ENABLED", "1")
    monkeypatch.setenv("OSU_LOCAL_NOTIFY_DONE_SHELL_CMD", "afplay /System/Library/Sounds/Glass.aiff")
    monkeypatch.setattr("host.audio.subprocess.run", fake_run)

    player = LocalAudioPlayer()

    assert player.play_agent_done() is True
    assert calls == [["/bin/sh", "-lc", "afplay /System/Library/Sounds/Glass.aiff"]]

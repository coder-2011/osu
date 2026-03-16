from pi.hardware import _resolve_sound_path


def test_resolve_sound_path_uses_override(monkeypatch) -> None:
    monkeypatch.setenv("OSU_SOUND_NOTIFY_WAV", "/tmp/custom.wav")
    assert _resolve_sound_path("OSU_SOUND_NOTIFY_WAV", "notify.wav") == "/tmp/custom.wav"


def test_resolve_sound_path_uses_base_dir(monkeypatch) -> None:
    monkeypatch.delenv("OSU_SOUND_NOTIFY_WAV", raising=False)
    monkeypatch.setenv("OSU_SOUND_BASE_DIR", "/home/pi/my-sounds")
    assert _resolve_sound_path("OSU_SOUND_NOTIFY_WAV", "notify.wav") == "/home/pi/my-sounds/notify.wav"

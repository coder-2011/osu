from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path


class LocalAudioPlayer:
    def __init__(self) -> None:
        self.enabled = os.getenv("OSU_LOCAL_AUDIO_ENABLED", "1").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        self.notify_wav = self._resolve_path("OSU_LOCAL_SOUND_NOTIFY_WAV", "notify.wav")
        self.success_wav = self._resolve_path("OSU_LOCAL_SOUND_SUCCESS_WAV", "success.wav")
        self.error_wav = self._resolve_path("OSU_LOCAL_SOUND_ERROR_WAV", "error.wav")
        self.player_cmd = self._resolve_player()
        self.notify_wav = self._resolve_notify_default(self.notify_wav)

    def play_notify(self) -> None:
        played = self._play(self.notify_wav)
        if not played:
            self.play_test_tone(
                frequency_hz=_env_int("OSU_LOCAL_NOTIFY_TONE_HZ", 1046),
                duration_ms=_env_int("OSU_LOCAL_NOTIFY_TONE_DURATION_MS", 140),
            )

    def play_success(self) -> None:
        played = self._play(self.success_wav)
        if not played:
            self.play_test_tone(
                frequency_hz=_env_int("OSU_LOCAL_SUCCESS_TONE_HZ", 1318),
                duration_ms=_env_int("OSU_LOCAL_SUCCESS_TONE_DURATION_MS", 180),
            )

    def play_error(self) -> None:
        played = self._play(self.error_wav)
        if not played:
            self.play_test_tone(
                frequency_hz=_env_int("OSU_LOCAL_ERROR_TONE_HZ", 220),
                duration_ms=_env_int("OSU_LOCAL_ERROR_TONE_DURATION_MS", 220),
            )

    def play_test_tone(self, frequency_hz: int | None = None, duration_ms: int | None = None) -> None:
        if not self.enabled or not self.player_cmd:
            return

        frequency = _clamp_int(frequency_hz or _env_int("OSU_LOCAL_TEST_TONE_HZ", 880), low=100, high=4000)
        duration = _clamp_int(duration_ms or _env_int("OSU_LOCAL_TEST_TONE_DURATION_MS", 180), low=50, high=3000)
        volume = _clamp_float(_env_float("OSU_LOCAL_TEST_TONE_VOLUME", 0.25), low=0.01, high=1.0)

        generated_wav: str | None = None
        try:
            generated_wav = self._generate_tone_wav(frequency_hz=frequency, duration_ms=duration, volume=volume)
            self._play(generated_wav)
        finally:
            if generated_wav:
                try:
                    Path(generated_wav).unlink(missing_ok=True)
                except Exception:
                    pass

    def _play(self, wav_path: str | None) -> bool:
        if not self.enabled or not self.player_cmd or not wav_path:
            return False

        path = Path(wav_path)
        if not path.exists():
            return False

        try:
            proc = subprocess.run(
                [self.player_cmd, str(path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
            return proc.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _generate_tone_wav(frequency_hz: int, duration_ms: int, volume: float) -> str:
        sample_rate = 44_100
        frame_count = max(1, int((duration_ms / 1000.0) * sample_rate))

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        with wave.open(wav_path, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)  # 16-bit PCM
            writer.setframerate(sample_rate)

            frames = bytearray()
            for index in range(frame_count):
                t = index / sample_rate
                sample = int(volume * 32767 * math.sin(2.0 * math.pi * frequency_hz * t))
                sample = max(-32768, min(32767, sample))
                frames.extend(struct.pack("<h", sample))
            writer.writeframes(bytes(frames))

        return wav_path

    @staticmethod
    def _resolve_player() -> str | None:
        override = os.getenv("OSU_LOCAL_AUDIO_PLAYER", "").strip()
        if override:
            return override

        for cmd in ("afplay", "aplay", "ffplay"):
            found = shutil.which(cmd)
            if found:
                return found
        return None

    @staticmethod
    def _resolve_path(env_key: str, default_name: str) -> str | None:
        override = os.getenv(env_key, "").strip()
        if override:
            return override

        base = os.getenv("OSU_LOCAL_SOUND_BASE_DIR", "sounds").strip() or "sounds"
        return str(Path(base) / default_name)

    @staticmethod
    def _resolve_notify_default(current: str | None) -> str | None:
        if not current:
            return current
        current_path = Path(current)
        if current_path.exists():
            return current

        repo_root = Path(__file__).resolve().parent.parent
        bundled = repo_root / "codex-notify-chime" / "assets" / "notify.mp3"
        if bundled.exists():
            return str(bundled)
        return current


def _clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _clamp_float(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default

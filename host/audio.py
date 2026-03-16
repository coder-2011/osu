from __future__ import annotations

import os
import shutil
import subprocess
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

    def play_notify(self) -> None:
        self._play(self.notify_wav)

    def play_success(self) -> None:
        self._play(self.success_wav)

    def play_error(self) -> None:
        self._play(self.error_wav)

    def _play(self, wav_path: str | None) -> None:
        if not self.enabled or not self.player_cmd or not wav_path:
            return

        path = Path(wav_path)
        if not path.exists():
            return

        try:
            subprocess.run(
                [self.player_cmd, str(path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
        except Exception:
            return

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

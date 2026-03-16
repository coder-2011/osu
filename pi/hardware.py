from __future__ import annotations

import atexit
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


class HardwareController(Protocol):
    def set_idle(self) -> None: ...

    def set_pending(self) -> None: ...

    def set_working(self) -> None: ...

    def indicate_notify(self) -> None: ...

    def indicate_success(self) -> None: ...

    def indicate_error(self) -> None: ...

    def set_button_callback(self, callback: Callable[[], None]) -> None: ...


@dataclass
class LoggingHardware:
    """Fallback controller when AIY libraries are unavailable."""

    logger: logging.Logger

    def set_idle(self) -> None:
        self.logger.info('{"hardware":"led","state":"idle"}')

    def set_pending(self) -> None:
        self.logger.info('{"hardware":"led","state":"pending"}')

    def set_working(self) -> None:
        self.logger.info('{"hardware":"led","state":"working"}')

    def indicate_notify(self) -> None:
        self.logger.info('{"hardware":"notify","event":"codex-turn"}')

    def indicate_success(self) -> None:
        self.logger.info('{"hardware":"commit","event":"success"}')

    def indicate_error(self) -> None:
        self.logger.info('{"hardware":"commit","event":"error"}')

    def set_button_callback(self, callback: Callable[[], None]) -> None:
        self.logger.info('{"hardware":"button","state":"callback-not-set-logging-fallback"}')


class AIYHardware:
    """Real AIY hardware controller with V1/V2 LED support and button callbacks."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._board = None
        self._leds = None
        self._led_api = "none"
        self._pattern = None
        self._color = None
        self._play_wav = None
        self._v1_led = None
        self._audio_enabled = os.getenv("OSU_PI_AUDIO_ENABLED", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        self._sound_notify = _resolve_sound_path("OSU_SOUND_NOTIFY_WAV", "notify.wav")
        self._sound_success = _resolve_sound_path("OSU_SOUND_SUCCESS_WAV", "success.wav")
        self._sound_error = _resolve_sound_path("OSU_SOUND_ERROR_WAV", "error.wav")

        self._init_audio()
        self._init_button_board()
        self._init_leds()

        atexit.register(self.close)

    def _init_audio(self) -> None:
        try:
            from aiy.voice.audio import play_wav  # type: ignore

            self._play_wav = play_wav
            self._logger.info('{"hardware":"audio","state":"ready"}')
        except Exception as err:  # pragma: no cover - hardware-dependent
            self._logger.warning(f'{{"hardware":"audio","state":"unavailable","error":"{err}"}}')

    def _init_button_board(self) -> None:
        try:
            from aiy.board import Board  # type: ignore

            board = Board()
            self._board = board.__enter__()
            self._logger.info('{"hardware":"button","state":"ready"}')
        except Exception as err:  # pragma: no cover - hardware-dependent
            self._board = None
            self._logger.warning(f'{{"hardware":"button","state":"unavailable","error":"{err}"}}')

    def _init_leds(self) -> None:
        try:
            from aiy.leds import Color, Leds, Pattern  # type: ignore

            leds = Leds()
            self._leds = leds.__enter__()
            self._pattern = Pattern
            self._color = Color
            self._led_api = "v2"
            self._logger.info('{"hardware":"led","state":"ready","api":"v2"}')
            return
        except Exception:
            self._leds = None

        try:
            from aiy.board import Led  # type: ignore

            self._v1_led = Led
            self._led_api = "v1"
            self._logger.info('{"hardware":"led","state":"ready","api":"v1"}')
        except Exception as err:  # pragma: no cover - hardware-dependent
            self._v1_led = None
            self._led_api = "none"
            self._logger.warning(f'{{"hardware":"led","state":"unavailable","error":"{err}"}}')

    def close(self) -> None:
        if self._leds is not None:
            try:
                self._leds.__exit__(None, None, None)
            except Exception:
                pass
            self._leds = None

        if self._board is not None:
            try:
                self._board.__exit__(None, None, None)
            except Exception:
                pass
            self._board = None

    def set_button_callback(self, callback: Callable[[], None]) -> None:
        if self._board is None:
            self._logger.warning('{"hardware":"button","state":"callback-unavailable"}')
            return

        try:
            self._board.button.when_pressed = callback
            self._logger.info('{"hardware":"button","state":"callback-registered"}')
        except Exception as err:  # pragma: no cover - hardware-dependent
            self._logger.warning(f'{{"hardware":"button","state":"callback-failed","error":"{err}"}}')

    def set_idle(self) -> None:
        if self._led_api == "v2" and self._leds is not None:
            self._leds.update(self._leds.rgb_off())
            return

        if self._led_api == "v1" and self._board is not None and self._v1_led is not None:
            self._board.led.state = self._v1_led.OFF

    def set_pending(self) -> None:
        if self._led_api == "v2" and self._leds is not None and self._pattern is not None and self._color is not None:
            self._leds.pattern = self._pattern.breathe(800)
            self._leds.update(self._leds.rgb_pattern(self._color.YELLOW))
            return

        if self._led_api == "v1" and self._board is not None and self._v1_led is not None:
            self._board.led.state = self._v1_led.PULSE_SLOW

    def set_working(self) -> None:
        if self._led_api == "v2" and self._leds is not None and self._pattern is not None and self._color is not None:
            self._leds.pattern = self._pattern.breathe(800)
            self._leds.update(self._leds.rgb_pattern(self._color.BLUE))
            return

        if self._led_api == "v1" and self._board is not None and self._v1_led is not None:
            self._board.led.state = self._v1_led.PULSE_QUICK

    def indicate_notify(self) -> None:
        if self._led_api == "v2" and self._leds is not None and self._color is not None:
            self._leds.update(self._leds.rgb_on(self._color.GREEN))
            time.sleep(0.15)
            self._leds.update(self._leds.rgb_off())
        elif self._led_api == "v1" and self._board is not None and self._v1_led is not None:
            self._board.led.state = self._v1_led.BLINK_3

        self._play_sound(self._sound_notify)

    def indicate_success(self) -> None:
        if self._led_api == "v2" and self._leds is not None and self._color is not None:
            self._leds.update(self._leds.rgb_on(self._color.GREEN))
            time.sleep(0.5)
        elif self._led_api == "v1" and self._board is not None and self._v1_led is not None:
            self._board.led.state = self._v1_led.ON
            time.sleep(0.5)

        self._play_sound(self._sound_success)

    def indicate_error(self) -> None:
        if self._led_api == "v2" and self._leds is not None and self._pattern is not None and self._color is not None:
            self._leds.pattern = self._pattern.blink(400)
            self._leds.update(self._leds.rgb_pattern(self._color.RED))
        elif self._led_api == "v1" and self._board is not None and self._v1_led is not None:
            self._board.led.state = self._v1_led.BLINK

        self._play_sound(self._sound_error)

    def _play_sound(self, path: str | None) -> None:
        if not self._audio_enabled:
            return

        if not path:
            return

        if not Path(path).exists():
            self._logger.warning(f'{{"hardware":"audio","state":"missing-file","path":"{path}"}}')
            return

        if self._play_wav is not None:
            try:
                self._play_wav(path)
                return
            except Exception as err:  # pragma: no cover - hardware-dependent
                self._logger.warning(f'{{"hardware":"audio","state":"play-failed","error":"{err}"}}')

        # Fallback playback path in case AIY audio helpers are unavailable.
        try:
            subprocess.run(
                ["aplay", path],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception as err:  # pragma: no cover - hardware-dependent
            self._logger.warning(f'{{"hardware":"audio","state":"fallback-play-failed","error":"{err}"}}')


def build_default_hardware(logger: logging.Logger) -> HardwareController:
    """Prefer AIY hardware controller; fallback to logging-only controller."""

    try:
        return AIYHardware(logger=logger)
    except Exception:  # pragma: no cover - hardware-dependent
        return LoggingHardware(logger=logger)


def _resolve_sound_path(env_var: str, default_filename: str) -> str | None:
    override = os.getenv(env_var, "").strip()
    if override:
        return override

    base = os.getenv("OSU_SOUND_BASE_DIR", "/home/pi/sounds").strip() or "/home/pi/sounds"
    return str(Path(base) / default_filename)

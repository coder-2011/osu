from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from dataclasses import dataclass
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
    """Fallback controller when GPIO is unavailable."""

    logger: logging.Logger
    idle_rgb: tuple[int, int, int] = (255, 140, 0)

    def set_idle(self) -> None:
        r, g, b = self.idle_rgb
        self.logger.info(f'{{"hardware":"led","state":"idle-orange","rgb":[{r},{g},{b}]}}')

    def set_pending(self) -> None:
        self.logger.info('{"hardware":"led","state":"pending-green"}')

    def set_working(self) -> None:
        self.logger.info('{"hardware":"led","state":"working-green-pulse"}')

    def indicate_notify(self) -> None:
        self.logger.info('{"hardware":"notify","event":"codex-turn"}')

    def indicate_success(self) -> None:
        self.logger.info('{"hardware":"commit","event":"success"}')

    def indicate_error(self) -> None:
        self.logger.info('{"hardware":"commit","event":"error"}')

    def set_button_callback(self, callback: Callable[[], None]) -> None:
        self.logger.info('{"hardware":"button","state":"callback-not-set-logging-fallback"}')


class GPIOHardware:
    """GPIO-only hardware controller for button + LED state machine."""

    _IDLE_COLOR = (100.0, 45.0, 0.0)  # orange
    _GREEN_COLOR = (0.0, 100.0, 0.0)
    _RED_COLOR = (100.0, 0.0, 0.0)

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._button_callback: Callable[[], None] | None = None
        self._state_lock = threading.Lock()
        self._pulse_thread: threading.Thread | None = None
        self._pulse_stop: threading.Event | None = None
        self._button_thread: threading.Thread | None = None
        self._button_stop: threading.Event | None = None
        self._button_event_backend = os.getenv("OSU_BUTTON_EVENT_BACKEND", "wait_for_edge").strip().lower()
        self._button_event_detect_enabled = False

        self._gpio = self._import_gpio()
        self._button_pin = _env_int("OSU_BUTTON_GPIO_PIN", 23)
        self._button_pull = os.getenv("OSU_BUTTON_GPIO_PULL", "up").strip().lower()
        self._button_edge = os.getenv("OSU_BUTTON_GPIO_EDGE", "auto").strip().lower()
        self._button_bouncetime_ms = _env_int("OSU_BUTTON_BOUNCETIME_MS", 150)
        self._button_edge_const = self._edge_const(self._button_edge, self._button_pull)

        self._mono_led_pin = _env_optional_int("OSU_LED_GPIO_PIN", 25)
        self._rgb_pins = (
            _env_optional_int("OSU_LED_RED_PIN"),
            _env_optional_int("OSU_LED_GREEN_PIN"),
            _env_optional_int("OSU_LED_BLUE_PIN"),
        )

        self._led_mode = "none"
        self._mono_high = False
        self._pwms: list[tuple[int, object]] = []

        self._gpio.setwarnings(False)
        self._gpio.setmode(self._gpio.BCM)
        self._init_button()
        self._init_leds()

        atexit.register(self.close)

    def _import_gpio(self):
        try:
            import RPi.GPIO as gpio  # type: ignore
        except Exception as err:
            raise RuntimeError(f"RPi.GPIO unavailable: {err}") from err
        return gpio

    def _init_button(self) -> None:
        pull_const = self._pull_const(self._button_pull)
        if pull_const is None:
            self._gpio.setup(self._button_pin, self._gpio.IN)
        else:
            self._gpio.setup(self._button_pin, self._gpio.IN, pull_up_down=pull_const)

        backend = self._button_event_backend
        if backend == "add_event_detect":
            self._gpio.add_event_detect(
                self._button_pin,
                self._button_edge_const,
                callback=self._on_button_edge,
                bouncetime=max(0, self._button_bouncetime_ms),
            )
            self._button_event_detect_enabled = True
        else:
            self._start_button_wait_loop()
            backend = "wait_for_edge"

        self._logger.info(
            (
                '{"hardware":"button","state":"ready","pin":%d,'
                '"pull":"%s","edge":"%s","bouncetime_ms":%d,"backend":"%s"}'
            )
            % (
                self._button_pin,
                self._button_pull,
                self._button_edge,
                self._button_bouncetime_ms,
                backend,
            )
        )

    def _init_leds(self) -> None:
        red, green, blue = self._rgb_pins
        if red is not None and green is not None and blue is not None:
            try:
                for pin in (red, green, blue):
                    self._gpio.setup(pin, self._gpio.OUT, initial=self._gpio.LOW)
                    pwm = self._gpio.PWM(pin, 200)
                    pwm.start(0.0)
                    self._pwms.append((pin, pwm))
                self._led_mode = "rgb"
                self._logger.info(
                    (
                        '{"hardware":"led","state":"ready","mode":"rgb",'
                        '"pins":{"red":%d,"green":%d,"blue":%d}}'
                    )
                    % (red, green, blue)
                )
                return
            except Exception as err:
                self._logger.warning(f'{{"hardware":"led","state":"rgb-unavailable","error":"{err}"}}')
                self._cleanup_pwms()

        if any(pin is not None for pin in (red, green, blue)):
            self._logger.warning(
                (
                    '{"hardware":"led","state":"rgb-config-incomplete",'
                    '"hint":"set OSU_LED_RED_PIN/OSU_LED_GREEN_PIN/OSU_LED_BLUE_PIN together"}'
                )
            )

        if self._mono_led_pin is not None:
            try:
                self._gpio.setup(self._mono_led_pin, self._gpio.OUT, initial=self._gpio.LOW)
                self._led_mode = "mono"
                self._logger.info(
                    (
                        '{"hardware":"led","state":"ready","mode":"mono","pin":%d}'
                    )
                    % self._mono_led_pin
                )
                return
            except Exception as err:
                self._logger.warning(f'{{"hardware":"led","state":"mono-unavailable","error":"{err}"}}')

        self._led_mode = "none"
        self._logger.warning('{"hardware":"led","state":"unavailable","mode":"none"}')

    def close(self) -> None:
        self._stop_pulse()
        self._stop_button_wait_loop()

        if self._button_event_detect_enabled:
            try:
                self._gpio.remove_event_detect(self._button_pin)
            except Exception:
                pass

        self._cleanup_pwms()

        pins_to_cleanup = [self._button_pin]
        if self._mono_led_pin is not None:
            pins_to_cleanup.append(self._mono_led_pin)
        pins_to_cleanup.extend(pin for pin in self._rgb_pins if pin is not None)

        for pin in sorted(set(pins_to_cleanup)):
            try:
                self._gpio.cleanup(pin)
            except Exception:
                pass

    def set_button_callback(self, callback: Callable[[], None]) -> None:
        self._button_callback = callback
        self._logger.info('{"hardware":"button","state":"callback-registered"}')

    def set_idle(self) -> None:
        self._set_static(self._IDLE_COLOR)

    def set_pending(self) -> None:
        self._set_static(self._GREEN_COLOR)

    def set_working(self) -> None:
        self._start_pulse(self._GREEN_COLOR)

    def indicate_notify(self) -> None:
        self._flash_color(self._GREEN_COLOR, flashes=1, flash_seconds=0.15, restore_color=self._IDLE_COLOR)

    def indicate_success(self) -> None:
        self._set_static(self._GREEN_COLOR)
        time.sleep(0.5)

    def indicate_error(self) -> None:
        self._start_pulse(self._RED_COLOR)

    def _on_button_edge(self, _channel: int) -> None:
        callback = self._button_callback
        if callback is None:
            return
        try:
            callback()
        except Exception as err:  # pragma: no cover - runtime callback safety
            self._logger.warning(f'{{"hardware":"button","state":"callback-failed","error":"{err}"}}')

    def _start_button_wait_loop(self) -> None:
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._button_wait_loop,
            kwargs={"stop_event": stop_event},
            name="gpio-button-wait-loop",
            daemon=True,
        )
        self._button_stop = stop_event
        self._button_thread = thread
        thread.start()

    def _stop_button_wait_loop(self) -> None:
        stop_event = self._button_stop
        thread = self._button_thread
        if stop_event is not None:
            stop_event.set()
        if thread is not None:
            thread.join(timeout=0.5)
        self._button_stop = None
        self._button_thread = None

    def _button_wait_loop(self, stop_event: threading.Event) -> None:
        timeout_ms = 200
        while not stop_event.is_set():
            channel = self._gpio.wait_for_edge(
                self._button_pin,
                self._button_edge_const,
                bouncetime=max(0, self._button_bouncetime_ms),
                timeout=timeout_ms,
            )
            if channel is None:
                continue
            self._on_button_edge(int(channel))

    def _set_static(self, color: tuple[float, float, float]) -> None:
        self._stop_pulse()
        with self._state_lock:
            self._apply_color(color)

    def _flash_color(
        self,
        color: tuple[float, float, float],
        flashes: int,
        flash_seconds: float,
        restore_color: tuple[float, float, float],
    ) -> None:
        self._stop_pulse()
        with self._state_lock:
            for _ in range(max(1, flashes)):
                self._apply_color(color)
                time.sleep(flash_seconds)
                self._apply_color((0.0, 0.0, 0.0))
                time.sleep(flash_seconds)
            self._apply_color(restore_color)

    def _start_pulse(self, base_color: tuple[float, float, float]) -> None:
        self._stop_pulse()

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._pulse_loop,
            kwargs={"base_color": base_color, "stop_event": stop_event},
            name="gpio-led-pulse",
            daemon=True,
        )
        self._pulse_stop = stop_event
        self._pulse_thread = thread
        thread.start()

    def _stop_pulse(self) -> None:
        stop_event = self._pulse_stop
        thread = self._pulse_thread

        if stop_event is not None:
            stop_event.set()
        if thread is not None:
            thread.join(timeout=1.0)

        self._pulse_stop = None
        self._pulse_thread = None

    def _pulse_loop(self, base_color: tuple[float, float, float], stop_event: threading.Event) -> None:
        if self._led_mode == "none":
            return

        levels = list(range(20, 101, 10)) + list(range(90, 9, -10))
        while not stop_event.is_set():
            for level in levels:
                if stop_event.is_set():
                    return
                scale = level / 100.0
                scaled = tuple(component * scale for component in base_color)
                with self._state_lock:
                    self._apply_color(scaled)
                time.sleep(0.05)

    def _apply_color(self, color: tuple[float, float, float]) -> None:
        if self._led_mode == "rgb":
            for component, (_, pwm) in zip(color, self._pwms):
                pwm.ChangeDutyCycle(max(0.0, min(100.0, float(component))))
            return

        if self._led_mode == "mono" and self._mono_led_pin is not None:
            turn_on = max(color) >= 50.0
            if turn_on != self._mono_high:
                self._gpio.output(self._mono_led_pin, self._gpio.HIGH if turn_on else self._gpio.LOW)
                self._mono_high = turn_on

    def _cleanup_pwms(self) -> None:
        for _, pwm in self._pwms:
            try:
                pwm.ChangeDutyCycle(0.0)
            except Exception:
                pass
            try:
                pwm.stop()
            except Exception:
                pass
        self._pwms.clear()

    def _pull_const(self, pull: str):
        pull = pull.strip().lower()
        if pull == "up":
            return self._gpio.PUD_UP
        if pull == "down":
            return self._gpio.PUD_DOWN
        return None

    def _edge_const(self, edge: str, pull: str):
        edge = edge.strip().lower()
        if edge == "falling":
            return self._gpio.FALLING
        if edge == "rising":
            return self._gpio.RISING
        if edge == "both":
            return self._gpio.BOTH
        # auto
        return self._gpio.FALLING if pull == "up" else self._gpio.RISING


def _env_optional_int(name: str, default: int | None = None) -> int | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return None if default is None else default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = _env_optional_int(name, default)
    return default if value is None else value


def build_default_hardware(logger: logging.Logger) -> HardwareController:
    """Prefer GPIO hardware controller; fallback to logging-only controller."""

    try:
        return GPIOHardware(logger=logger)
    except Exception as err:  # pragma: no cover - runtime hardware dependency
        logger.warning(f'{{"hardware":"gpio","state":"unavailable","error":"{err}"}}')
        return LoggingHardware(logger=logger)

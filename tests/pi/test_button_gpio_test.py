from __future__ import annotations

import io
from typing import Callable

from pi.button_gpio_test import MonitorConfig, main, parse_args, run_monitor


class FakeGPIO:
    BCM = "bcm"
    IN = "in"
    PUD_UP = "pud_up"
    PUD_DOWN = "pud_down"
    FALLING = "falling"
    RISING = "rising"
    BOTH = "both"

    def __init__(self, events: list[int] | None = None) -> None:
        self.events = events or []
        self.mode = None
        self.setup_args = None
        self.setup_kwargs = None
        self.wait_calls: list[tuple[int, str, int]] = []
        self.cleanup_pin = None
        self.warnings = None

    def setwarnings(self, enabled: bool) -> None:
        self.warnings = enabled

    def setmode(self, mode: str) -> None:
        self.mode = mode

    def setup(self, *args, **kwargs) -> None:
        self.setup_args = args
        self.setup_kwargs = kwargs

    def wait_for_edge(self, pin: int, edge: str, bouncetime: int):
        self.wait_calls.append((pin, edge, bouncetime))
        if self.events:
            return self.events.pop(0)
        raise KeyboardInterrupt

    def cleanup(self, pin: int) -> None:
        self.cleanup_pin = pin


def test_parse_args_auto_edge_uses_falling_for_pull_up() -> None:
    cfg = parse_args(["--pin", "23", "--pull", "up", "--edge", "auto", "--once"])

    assert cfg == MonitorConfig(
        pin=23,
        pull="up",
        edge="falling",
        bouncetime_ms=150,
        once=True,
        led_green=True,
    )


def test_parse_args_auto_edge_uses_rising_for_pull_down() -> None:
    cfg = parse_args(["--pin", "17", "--pull", "down", "--edge", "auto", "--once"])

    assert cfg == MonitorConfig(
        pin=17,
        pull="down",
        edge="rising",
        bouncetime_ms=150,
        once=True,
        led_green=True,
    )


def test_run_monitor_prints_press_and_cleans_up() -> None:
    fake_gpio = FakeGPIO(events=[23])
    stdout = io.StringIO()
    cfg = MonitorConfig(
        pin=23,
        pull="up",
        edge="falling",
        bouncetime_ms=120,
        once=True,
        led_green=True,
    )
    events: list[str] = []

    def fake_led_initializer(_stdout) -> Callable[[], None] | None:
        events.append("led_on")

        def cleanup() -> None:
            events.append("led_off")

        return cleanup

    status = run_monitor(cfg, fake_gpio, stdout, led_initializer=fake_led_initializer)

    output = stdout.getvalue()
    assert status == 0
    assert "waiting_for_button pin=23 pull=up edge=falling bouncetime_ms=120" in output
    assert "button_press pin=23 count=1" in output
    assert fake_gpio.mode == fake_gpio.BCM
    assert fake_gpio.setup_args == (23, fake_gpio.IN)
    assert fake_gpio.setup_kwargs == {"pull_up_down": fake_gpio.PUD_UP}
    assert fake_gpio.wait_calls == [(23, fake_gpio.FALLING, 120)]
    assert fake_gpio.cleanup_pin == 23
    assert events == ["led_on", "led_off"]


def test_main_returns_error_when_gpio_import_fails(monkeypatch) -> None:
    stdout = io.StringIO()
    monkeypatch.setattr("pi.button_gpio_test._import_gpio", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    status = main(["--once"], stdout=stdout)

    assert status == 2
    assert "boom" in stdout.getvalue()


def test_parse_args_allows_disabling_green_led() -> None:
    cfg = parse_args(["--no-led-green"])

    assert cfg.led_green is False

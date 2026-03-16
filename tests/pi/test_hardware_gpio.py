from __future__ import annotations

import logging
import sys
import time
import types

from pi.hardware import GPIOHardware, LoggingHardware, build_default_hardware


class FakePWM:
    def __init__(self, pin: int, freq: int) -> None:
        self.pin = pin
        self.freq = freq
        self.started = False
        self.duty_cycle = 0.0
        self.stopped = False

    def start(self, duty_cycle: float) -> None:
        self.started = True
        self.duty_cycle = duty_cycle

    def ChangeDutyCycle(self, duty_cycle: float) -> None:
        self.duty_cycle = duty_cycle

    def stop(self) -> None:
        self.stopped = True


class FakeGPIO:
    BCM = "BCM"
    IN = "IN"
    OUT = "OUT"
    PUD_UP = "PUD_UP"
    PUD_DOWN = "PUD_DOWN"
    FALLING = "FALLING"
    RISING = "RISING"
    BOTH = "BOTH"
    LOW = 0
    HIGH = 1

    def __init__(self) -> None:
        self.warnings = True
        self.mode = None
        self.setup_calls: list[tuple[tuple, dict]] = []
        self.event_callbacks: dict[int, object] = {}
        self.output_state: dict[int, int] = {}
        self.pwms: dict[int, FakePWM] = {}
        self.cleanup_calls: list[int] = []
        self.event_remove_calls: list[int] = []

    def setwarnings(self, enabled: bool) -> None:
        self.warnings = enabled

    def setmode(self, mode: str) -> None:
        self.mode = mode

    def setup(self, *args, **kwargs) -> None:
        self.setup_calls.append((args, kwargs))
        pin = int(args[0])
        if "initial" in kwargs:
            self.output_state[pin] = kwargs["initial"]

    def add_event_detect(self, pin: int, edge, callback, bouncetime: int) -> None:
        self.event_callbacks[int(pin)] = callback

    def remove_event_detect(self, pin: int) -> None:
        self.event_remove_calls.append(int(pin))
        self.event_callbacks.pop(int(pin), None)

    def output(self, pin: int, value: int) -> None:
        self.output_state[int(pin)] = value

    def PWM(self, pin: int, freq: int) -> FakePWM:
        pwm = FakePWM(pin=pin, freq=freq)
        self.pwms[int(pin)] = pwm
        return pwm

    def cleanup(self, pin: int) -> None:
        self.cleanup_calls.append(int(pin))

    def trigger_edge(self, pin: int) -> None:
        callback = self.event_callbacks.get(int(pin))
        if callback is not None:
            callback(int(pin))


def _install_fake_gpio_module(monkeypatch, fake_gpio: FakeGPIO) -> None:
    fake_rpi_module = types.ModuleType("RPi")
    fake_gpio_module = types.ModuleType("RPi.GPIO")

    for key, value in fake_gpio.__class__.__dict__.items():
        if key.isupper():
            setattr(fake_gpio_module, key, value)

    # Bind instance methods as module callables.
    for method_name in (
        "setwarnings",
        "setmode",
        "setup",
        "add_event_detect",
        "remove_event_detect",
        "output",
        "PWM",
        "cleanup",
    ):
        setattr(fake_gpio_module, method_name, getattr(fake_gpio, method_name))

    fake_rpi_module.GPIO = fake_gpio_module

    monkeypatch.setitem(sys.modules, "RPi", fake_rpi_module)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", fake_gpio_module)


def test_gpio_hardware_button_callback_and_mono_led(monkeypatch) -> None:
    fake_gpio = FakeGPIO()
    _install_fake_gpio_module(monkeypatch, fake_gpio)

    monkeypatch.setenv("OSU_BUTTON_GPIO_PIN", "23")
    monkeypatch.setenv("OSU_BUTTON_GPIO_PULL", "up")
    monkeypatch.setenv("OSU_BUTTON_GPIO_EDGE", "auto")
    monkeypatch.setenv("OSU_LED_GPIO_PIN", "25")
    monkeypatch.delenv("OSU_LED_RED_PIN", raising=False)
    monkeypatch.delenv("OSU_LED_GREEN_PIN", raising=False)
    monkeypatch.delenv("OSU_LED_BLUE_PIN", raising=False)

    pulse_calls: list[tuple[float, float, float]] = []

    def fake_pulse_loop(self, base_color, stop_event) -> None:
        pulse_calls.append(base_color)
        stop_event.wait(0.01)

    monkeypatch.setattr(GPIOHardware, "_pulse_loop", fake_pulse_loop)

    hw = GPIOHardware(logger=logging.getLogger("test-gpio-mono"))

    presses = {"count": 0}
    hw.set_button_callback(lambda: presses.__setitem__("count", presses["count"] + 1))
    fake_gpio.trigger_edge(23)

    hw.set_idle()
    hw.set_pending()
    hw.set_working()
    time.sleep(0.02)
    hw.set_idle()
    hw.close()

    assert presses["count"] == 1
    assert fake_gpio.mode == fake_gpio.BCM
    assert fake_gpio.output_state[25] == fake_gpio.HIGH
    assert pulse_calls[-1] == GPIOHardware._GREEN_COLOR
    assert 23 in fake_gpio.event_remove_calls


def test_gpio_hardware_rgb_mode_sets_expected_colors(monkeypatch) -> None:
    fake_gpio = FakeGPIO()
    _install_fake_gpio_module(monkeypatch, fake_gpio)

    monkeypatch.setenv("OSU_LED_GPIO_PIN", "")
    monkeypatch.setenv("OSU_LED_RED_PIN", "17")
    monkeypatch.setenv("OSU_LED_GREEN_PIN", "27")
    monkeypatch.setenv("OSU_LED_BLUE_PIN", "22")

    hw = GPIOHardware(logger=logging.getLogger("test-gpio-rgb"))
    hw.set_idle()

    assert fake_gpio.pwms[17].duty_cycle == 100.0
    assert fake_gpio.pwms[27].duty_cycle == 45.0
    assert fake_gpio.pwms[22].duty_cycle == 0.0

    hw.set_pending()
    assert fake_gpio.pwms[17].duty_cycle == 0.0
    assert fake_gpio.pwms[27].duty_cycle == 100.0
    assert fake_gpio.pwms[22].duty_cycle == 0.0
    hw.close()


def test_build_default_hardware_falls_back_to_logging(monkeypatch) -> None:
    def raise_init(self, logger) -> None:
        raise RuntimeError("gpio init failed")

    monkeypatch.setattr(GPIOHardware, "__init__", raise_init)

    hardware = build_default_hardware(logging.getLogger("test-fallback"))
    assert isinstance(hardware, LoggingHardware)

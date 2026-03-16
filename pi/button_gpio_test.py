from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, TextIO


@dataclass(frozen=True)
class MonitorConfig:
    pin: int
    pull: str
    edge: str
    bouncetime_ms: int
    once: bool
    led_green: bool


def _default_pin() -> int:
    raw = os.getenv("OSU_BUTTON_GPIO_PIN", "23")
    try:
        return int(raw)
    except ValueError:
        return 23


def parse_args(argv: list[str] | None = None) -> MonitorConfig:
    parser = argparse.ArgumentParser(
        description="Minimal GPIO button test for Raspberry Pi/AIY.",
    )
    parser.add_argument(
        "--pin",
        type=int,
        default=_default_pin(),
        help="BCM GPIO pin number used by the button (default: 23 or OSU_BUTTON_GPIO_PIN).",
    )
    parser.add_argument(
        "--pull",
        choices=("up", "down", "off"),
        default=os.getenv("OSU_BUTTON_GPIO_PULL", "up").lower(),
        help="Internal pull resistor configuration (default: up).",
    )
    parser.add_argument(
        "--edge",
        choices=("auto", "falling", "rising", "both"),
        default=os.getenv("OSU_BUTTON_GPIO_EDGE", "auto").lower(),
        help="Edge to detect; use auto to infer from pull config (default: auto).",
    )
    parser.add_argument(
        "--bouncetime-ms",
        type=int,
        default=int(os.getenv("OSU_BUTTON_BOUNCETIME_MS", "150")),
        help="Debounce time in milliseconds (default: 150).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Exit after the first detected press.",
    )
    parser.add_argument(
        "--no-led-green",
        action="store_true",
        help="Disable AIY LED green idle indicator while monitoring.",
    )

    args = parser.parse_args(argv)
    edge = args.edge
    if edge == "auto":
        edge = "falling" if args.pull == "up" else "rising"

    return MonitorConfig(
        pin=args.pin,
        pull=args.pull,
        edge=edge,
        bouncetime_ms=max(0, args.bouncetime_ms),
        once=bool(args.once),
        led_green=not bool(args.no_led_green),
    )


def _import_gpio() -> Any:
    try:
        import RPi.GPIO as gpio  # type: ignore
    except Exception as err:  # pragma: no cover - import depends on Pi runtime
        raise RuntimeError(
            "Failed to import RPi.GPIO. Run this on Raspberry Pi with GPIO support."
        ) from err
    return gpio


def _pull_const(gpio: Any, pull: str) -> Any | None:
    if pull == "up":
        return gpio.PUD_UP
    if pull == "down":
        return gpio.PUD_DOWN
    return None


def _edge_const(gpio: Any, edge: str) -> Any:
    if edge == "falling":
        return gpio.FALLING
    if edge == "rising":
        return gpio.RISING
    return gpio.BOTH


def _enable_green_led(stdout: TextIO) -> Callable[[], None] | None:
    try:
        from aiy.leds import Color, Leds  # type: ignore

        leds = Leds()
        active_leds = leds.__enter__()
        active_leds.update(active_leds.rgb_on(Color.GREEN))
        print("led_state=green", file=stdout, flush=True)

        def _cleanup() -> None:
            try:
                active_leds.update(active_leds.rgb_off())
            finally:
                leds.__exit__(None, None, None)

        return _cleanup
    except Exception:
        return None


def run_monitor(
    cfg: MonitorConfig,
    gpio: Any,
    stdout: TextIO,
    led_initializer: Callable[[TextIO], Callable[[], None] | None] = _enable_green_led,
) -> int:
    pull_const = _pull_const(gpio, cfg.pull)
    edge_const = _edge_const(gpio, cfg.edge)
    led_cleanup: Callable[[], None] | None = None

    gpio.setwarnings(False)
    gpio.setmode(gpio.BCM)
    if pull_const is None:
        gpio.setup(cfg.pin, gpio.IN)
    else:
        gpio.setup(cfg.pin, gpio.IN, pull_up_down=pull_const)

    print(
        (
            "waiting_for_button "
            f"pin={cfg.pin} pull={cfg.pull} edge={cfg.edge} bouncetime_ms={cfg.bouncetime_ms}"
        ),
        file=stdout,
        flush=True,
    )
    if cfg.led_green:
        led_cleanup = led_initializer(stdout)

    count = 0
    try:
        while True:
            channel = gpio.wait_for_edge(
                cfg.pin,
                edge_const,
                bouncetime=cfg.bouncetime_ms,
            )
            if channel is None:
                continue
            count += 1
            print(
                f"button_press pin={channel} count={count} ts={time.time():.3f}",
                file=stdout,
                flush=True,
            )
            if cfg.once:
                return 0
    except KeyboardInterrupt:
        print("stopped", file=stdout, flush=True)
        return 0
    finally:
        if led_cleanup is not None:
            led_cleanup()
        gpio.cleanup(cfg.pin)


def main(argv: list[str] | None = None, stdout: TextIO | None = None) -> int:
    out = stdout or sys.stdout
    cfg = parse_args(argv)
    try:
        gpio = _import_gpio()
    except RuntimeError as err:
        print(str(err), file=out, flush=True)
        return 2
    return run_monitor(cfg, gpio, out)


if __name__ == "__main__":
    raise SystemExit(main())

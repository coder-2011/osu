from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol


class HardwareController(Protocol):
    def set_idle(self) -> None: ...

    def set_pending(self) -> None: ...

    def set_working(self) -> None: ...

    def indicate_notify(self) -> None: ...

    def indicate_success(self) -> None: ...

    def indicate_error(self) -> None: ...


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


def build_default_hardware(logger: logging.Logger) -> HardwareController:
    """Use logging fallback until AIY hardware wiring module is added."""

    return LoggingHardware(logger=logger)

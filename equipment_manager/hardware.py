from __future__ import annotations

import logging
import threading
import time

from flask import current_app


logger = logging.getLogger(__name__)


class NullIndicator:
    def success(self) -> None:
        return None

    def error(self) -> None:
        return None


class GpioIndicator:
    def __init__(self, green_pin: int, red_pin: int, buzzer_pin: int):
        try:
            from gpiozero import Buzzer, LED
        except ImportError as exc:
            raise RuntimeError("gpiozero 패키지가 설치되어 있지 않습니다.") from exc
        self.green = LED(green_pin)
        self.red = LED(red_pin)
        self.buzzer = Buzzer(buzzer_pin)

    def _pulse(self, led, beep_count: int) -> None:
        def run():
            led.on()
            for _ in range(beep_count):
                self.buzzer.on()
                time.sleep(0.08)
                self.buzzer.off()
                time.sleep(0.08)
            time.sleep(0.45)
            led.off()

        threading.Thread(target=run, daemon=True).start()

    def success(self) -> None:
        self._pulse(self.green, 1)

    def error(self) -> None:
        self._pulse(self.red, 2)


def get_indicator():
    indicator = current_app.extensions.get("status_indicator")
    if indicator is not None:
        return indicator
    if current_app.config["GPIO_ENABLED"]:
        try:
            indicator = GpioIndicator(
                current_app.config["GPIO_GREEN_PIN"],
                current_app.config["GPIO_RED_PIN"],
                current_app.config["GPIO_BUZZER_PIN"],
            )
        except Exception:
            logger.exception("GPIO indicator initialization failed")
            indicator = NullIndicator()
    else:
        indicator = NullIndicator()
    current_app.extensions["status_indicator"] = indicator
    return indicator

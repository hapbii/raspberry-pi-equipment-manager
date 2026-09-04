from __future__ import annotations

import logging
import queue
import threading

from flask import current_app


logger = logging.getLogger(__name__)


class NullIndicator:
    def success(self) -> None:
        return None

    def error(self) -> None:
        return None

    def close(self) -> None:
        return None


class GpioIndicator:
    """한 개의 고정 worker로 LED와 부저 이벤트를 순서대로 처리합니다."""

    def __init__(self, green_pin: int, red_pin: int, buzzer_pin: int):
        try:
            from gpiozero import Buzzer, LED
        except ImportError as exc:
            raise RuntimeError("gpiozero 패키지가 설치되어 있지 않습니다.") from exc

        devices = []
        try:
            green = LED(green_pin)
            devices.append(green)
            red = LED(red_pin)
            devices.append(red)
            buzzer = Buzzer(buzzer_pin)
            devices.append(buzzer)
        except Exception:
            for device in devices:
                try:
                    device.close()
                except Exception:
                    logger.debug("GPIO cleanup after initialization failure failed", exc_info=True)
            raise

        self.green = green
        self.red = red
        self.buzzer = buzzer
        self._events: queue.Queue[tuple[object, int]] = queue.Queue(maxsize=4)
        self._stop_event = threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False
        self._worker = threading.Thread(
            target=self._run,
            name="gpio-indicator",
            daemon=True,
        )
        self._worker.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                event = self._events.get(timeout=0.5)
            except queue.Empty:
                continue
            led, beep_count = event
            try:
                led.on()
                for _ in range(beep_count):
                    self.buzzer.on()
                    if self._stop_event.wait(0.08):
                        break
                    self.buzzer.off()
                    if self._stop_event.wait(0.08):
                        break
                self._stop_event.wait(0.45)
            except Exception:
                logger.exception("GPIO indicator event failed")
            finally:
                for device in (self.buzzer, led):
                    try:
                        device.off()
                    except Exception:
                        logger.debug("GPIO device off failed", exc_info=True)
                self._events.task_done()

    def _enqueue(self, led, beep_count: int) -> None:
        with self._close_lock:
            if self._closed:
                return
            try:
                self._events.put_nowait((led, beep_count))
            except queue.Full:
                logger.warning("GPIO indicator queue is full; dropping an event")

    def success(self) -> None:
        self._enqueue(self.green, 1)

    def error(self) -> None:
        self._enqueue(self.red, 2)

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._stop_event.set()
        if self._worker.is_alive() and threading.current_thread() is not self._worker:
            self._worker.join(timeout=2)
        while True:
            try:
                self._events.get_nowait()
                self._events.task_done()
            except queue.Empty:
                break
        for device in (self.green, self.red, self.buzzer):
            try:
                device.off()
                device.close()
            except Exception:
                logger.debug("GPIO device close failed", exc_info=True)


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

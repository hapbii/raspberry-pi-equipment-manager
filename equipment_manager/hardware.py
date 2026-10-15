from __future__ import annotations

import logging
import queue
import threading

from flask import current_app

from .resources import release_error_frames


logger = logging.getLogger(__name__)
INDICATOR_LOCK_KEY = "status_indicator_lock"
INDICATOR_KEY = "status_indicator"
INDICATOR_CLOSED_KEY = "status_indicator_closed"


def _close_devices(devices) -> None:
    interrupted = None
    device = None
    try:
        for device in devices:
            # Always attempt both operations on every device, even when off()
            # fails or cleanup is interrupted. Keep the first interrupt.
            for operation in ("off", "close"):
                try:
                    getattr(device, operation)()
                except BaseException as exc:
                    release_error_frames(exc)
                    if isinstance(exc, Exception):
                        logger.debug("GPIO device %s during cleanup failed", operation, exc_info=True)
                    elif interrupted is None:
                        interrupted = exc
        if interrupted is not None:
            raise interrupted
    finally:
        # Closed GPIO wrappers may still own Python-side buffers. Do not pin
        # the whole device collection through a saved cleanup traceback.
        devices = device = None


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

        # Allocate bookkeeping before opening GPIO handles: allocation failures
        # must not strand already-open LEDs or buzzers.
        self._events: queue.Queue[tuple[object, int]] = queue.Queue(maxsize=4)
        self._stop_event = threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False
        self._worker = threading.Thread(
            target=self._run,
            name="gpio-indicator",
            daemon=True,
        )
        devices = []
        devices_adopted = False
        try:
            devices.append(LED(green_pin))
            devices.append(LED(red_pin))
            devices.append(Buzzer(buzzer_pin))
            self.green, self.red, self.buzzer = devices
            devices_adopted = True
            self._worker.start()
        except BaseException as exc:
            release_error_frames(exc)
            try:
                if devices_adopted:
                    self.close()
                else:
                    _close_devices(devices)
            except BaseException as cleanup_error:
                release_error_frames(cleanup_error)
                raise
            finally:
                # A failed constructor has no owner to dispose of it later.
                # The worker's bound target forms a collectable cycle only
                # after this retained traceback drops the partial instance.
                self = None
            raise
        finally:
            devices = None

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
        try:
            if self._worker.is_alive() and threading.current_thread() is not self._worker:
                self._worker.join(timeout=2)
        finally:
            try:
                while True:
                    try:
                        self._events.get_nowait()
                        self._events.task_done()
                    except queue.Empty:
                        break
            finally:
                _close_devices((self.green, self.red, self.buzzer))


def init_hardware(app) -> None:
    """요청이 동시에 시작되어도 표시기는 한 번만 생성되도록 준비합니다."""
    app.extensions[INDICATOR_LOCK_KEY] = threading.Lock()
    app.extensions[INDICATOR_CLOSED_KEY] = False


def close_hardware(app) -> None:
    """Close exactly once and prevent late requests from reopening devices."""
    lock = app.extensions.get(INDICATOR_LOCK_KEY)
    if lock is None:
        return
    with lock:
        app.extensions[INDICATOR_CLOSED_KEY] = True
        indicator = app.extensions.pop(INDICATOR_KEY, None)
    if indicator is not None:
        indicator.close()


def get_indicator():
    if current_app.extensions.get(INDICATOR_CLOSED_KEY):
        return NullIndicator()
    indicator = current_app.extensions.get(INDICATOR_KEY)
    if indicator is not None:
        return indicator

    lock = current_app.extensions[INDICATOR_LOCK_KEY]
    with lock:
        if current_app.extensions.get(INDICATOR_CLOSED_KEY):
            return NullIndicator()
        indicator = current_app.extensions.get(INDICATOR_KEY)
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
        current_app.extensions[INDICATOR_KEY] = indicator
        return indicator

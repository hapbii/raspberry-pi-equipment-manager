from __future__ import annotations

import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from equipment_manager import create_app
from equipment_manager.hardware import (
    INDICATOR_KEY, GpioIndicator, NullIndicator, close_hardware, get_indicator, init_hardware,
)


class FakeDevice:
    instances = []

    def __init__(self, pin):
        self.pin = pin
        self.closed = False
        self.active = False
        self.instances.append(self)

    def on(self):
        self.active = True

    def off(self):
        self.active = False

    def close(self):
        self.closed = True


class GpioIndicatorTestCase(unittest.TestCase):
    def setUp(self):
        FakeDevice.instances = []
        module = types.ModuleType("gpiozero")
        module.LED = FakeDevice
        module.Buzzer = FakeDevice
        self.module_patch = patch.dict(sys.modules, {"gpiozero": module})
        self.module_patch.start()

    def tearDown(self):
        self.module_patch.stop()

    def test_queue_is_bounded_and_close_releases_devices(self):
        indicator = GpioIndicator(17, 27, 22)
        with patch("equipment_manager.hardware.logger.warning"):
            for _ in range(20):
                indicator.success()
        self.assertLessEqual(indicator._events.qsize(), 4)

        indicator.close()
        indicator.close()

        self.assertFalse(indicator._worker.is_alive())
        self.assertEqual(indicator._events.qsize(), 0)
        self.assertTrue(all(device.closed for device in FakeDevice.instances))

    def test_partial_initialization_releases_already_opened_gpio(self):
        created = []

        def failing_led(pin):
            if created:
                raise RuntimeError("second LED failed")
            device = FakeDevice(pin)
            created.append(device)
            return device

        module = types.ModuleType("gpiozero")
        module.LED = failing_led
        module.Buzzer = FakeDevice
        with patch.dict(sys.modules, {"gpiozero": module}):
            with self.assertRaises(RuntimeError):
                GpioIndicator(17, 27, 22)

        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].closed)

    def test_worker_start_failure_releases_devices(self):
        with patch("equipment_manager.hardware.threading.Thread.start", side_effect=RuntimeError("no threads")):
            with self.assertRaisesRegex(RuntimeError, "no threads"):
                GpioIndicator(17, 27, 22)
        self.assertEqual(len(FakeDevice.instances), 3)
        self.assertTrue(all(device.closed for device in FakeDevice.instances))

    def test_off_failure_does_not_skip_device_close(self):
        indicator = GpioIndicator(17, 27, 22)
        with patch.object(indicator.green, "off", side_effect=RuntimeError("disconnected")):
            indicator.close()
        self.assertTrue(all(device.closed for device in FakeDevice.instances))
        self.assertFalse(indicator._worker.is_alive())

    def test_queue_allocation_failure_does_not_open_gpio_handles(self):
        with patch("equipment_manager.hardware.queue.Queue", side_effect=MemoryError):
            with self.assertRaises(MemoryError):
                GpioIndicator(17, 27, 22)
        self.assertEqual(FakeDevice.instances, [])

    def test_app_shutdown_prevents_late_requests_from_reopening_gpio(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({
                "TESTING": True, "GPIO_ENABLED": True, "DETECTOR_MODE": "mock",
                "HEARTBEAT_ENABLED": False,
                "DATABASE": str(Path(directory) / "test.db"),
                "ERROR_LOG_PATH": str(Path(directory) / "errors.log"),
            })
            try:
                with app.app_context():
                    first = get_indicator()
                    app.extensions["shutdown_services"]()
                    for _ in range(100):
                        late = get_indicator()
                        self.assertIsInstance(late, NullIndicator)
                        late.success()
                    self.assertNotIn(INDICATOR_KEY, app.extensions)
                    self.assertEqual(len(FakeDevice.instances), 3)
                    self.assertTrue(all(device.closed for device in FakeDevice.instances))
                    self.assertFalse(first._worker.is_alive())
            finally:
                close_hardware(app)
                app.extensions["shutdown_services"]()

    def test_concurrent_initialization_and_shutdown_close_new_indicator(self):
        app = Flask(__name__)
        app.config.update(GPIO_ENABLED=True, GPIO_GREEN_PIN=17, GPIO_RED_PIN=27, GPIO_BUZZER_PIN=22)
        init_hardware(app)
        entering = threading.Event()
        release = threading.Event()
        closed = threading.Event()

        class SlowIndicator:
            def __init__(self, *_args):
                entering.set()
                release.wait(timeout=2)

            def close(self):
                closed.set()

        def request_indicator():
            with app.app_context():
                get_indicator()

        with patch("equipment_manager.hardware.GpioIndicator", SlowIndicator):
            requester = threading.Thread(target=request_indicator)
            stopper = threading.Thread(target=close_hardware, args=(app,))
            requester.start()
            try:
                self.assertTrue(entering.wait(timeout=2))
                stopper.start()
            finally:
                release.set()
                requester.join(timeout=2)
                if stopper.ident is not None:
                    stopper.join(timeout=2)
                close_hardware(app)
            self.assertFalse(requester.is_alive())
            self.assertFalse(stopper.is_alive())
            self.assertTrue(closed.is_set())
            self.assertNotIn(INDICATOR_KEY, app.extensions)
            with app.app_context():
                self.assertIsInstance(get_indicator(), NullIndicator)

    def test_concurrent_first_requests_share_one_indicator(self):
        app = Flask(__name__)
        app.config.update(
            GPIO_ENABLED=True,
            GPIO_GREEN_PIN=17,
            GPIO_RED_PIN=27,
            GPIO_BUZZER_PIN=22,
        )
        init_hardware(app)
        barrier = threading.Barrier(8)
        created = []
        returned = []

        class SlowIndicator:
            def __init__(self, *_args):
                time.sleep(0.02)
                created.append(self)

            def close(self):
                return None

        def request_indicator():
            with app.app_context():
                barrier.wait(timeout=1)
                returned.append(get_indicator())

        with patch("equipment_manager.hardware.GpioIndicator", SlowIndicator):
            workers = [threading.Thread(target=request_indicator) for _ in range(8)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=2)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(len(created), 1)
        self.assertEqual(len(returned), 8)
        self.assertTrue(all(indicator is created[0] for indicator in returned))


if __name__ == "__main__":
    unittest.main()

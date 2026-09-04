from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from equipment_manager.hardware import GpioIndicator


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


if __name__ == "__main__":
    unittest.main()

import ctypes
import os
import unittest
from unittest.mock import patch

from equipment_manager.system_metrics import current_rss_mb


class SystemMetricsTest(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows API resource regression')
    def test_repeated_rss_reads_reuse_windows_api_bindings(self):
        with patch('ctypes.WinDLL', wraps=ctypes.WinDLL) as load_library:
            for _ in range(200):
                self.assertGreater(current_rss_mb(), 0)
        self.assertLessEqual(load_library.call_count, 2)


if __name__ == '__main__':
    unittest.main()

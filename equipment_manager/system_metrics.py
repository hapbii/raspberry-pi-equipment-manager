from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _windows_memory_api():
    """Keep one structure/pointer type and API binding for all RSS reads."""
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
            ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
            ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
            ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
            ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    get_process = kernel32.GetCurrentProcess
    get_process.restype = wintypes.HANDLE
    get_memory = psapi.GetProcessMemoryInfo
    get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
    get_memory.restype = wintypes.BOOL
    return ProcessMemoryCounters, get_process, get_memory


def current_rss_mb() -> float | None:
    """현재 프로세스 RSS를 반환합니다. Linux에서는 /proc을 사용합니다."""
    status_path = Path("/proc/self/status")
    if status_path.exists():
        try:
            with status_path.open(encoding="ascii") as status_file:
                for line in status_file:
                    if line.startswith("VmRSS:"):
                        return round(int(line.split()[1]) / 1024, 1)
        except (OSError, ValueError, IndexError):
            return None
    if os.name == "nt":
        try:
            import ctypes
            counters_type, get_process, get_memory = _windows_memory_api()
            counters = counters_type()
            counters.cb = ctypes.sizeof(counters)
            if get_memory(get_process(), ctypes.byref(counters), counters.cb):
                return round(counters.WorkingSetSize / (1024 * 1024), 1)
        except (AttributeError, OSError, ctypes.ArgumentError):
            return None
    return None

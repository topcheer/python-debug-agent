"""System inspector: process info, CPU, disk, network."""

from __future__ import annotations

import os
import platform
import socket
import sys
import time

from debug_agent.tool_registry import debug_tool, ToolParam


@debug_tool("get_process_info", "Get process info: PID, CPU usage, memory limits, container detection")
def get_process_info() -> dict:
    try:
        import resource
        cpu_time = resource.getrusage(resource.RUSAGE_SELF)
        cpu_user = cpu_time.ru_utime
        cpu_sys = cpu_time.ru_stime
    except ImportError:
        cpu_user = cpu_sys = 0

    # Container detection
    in_container = os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")
    try:
        with open("/proc/1/cgroup", "t") as f:
            if "docker" in f.read() or "kubepods" in f.read():
                in_container = True
    except (FileNotFoundError, IOError):
        pass

    return {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "cpu_time": {"user_seconds": round(cpu_user, 2), "system_seconds": round(cpu_sys, 2)},
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "in_container": in_container,
    }


@debug_tool("get_system_info", "Get system information: OS, CPU cores, load average")
def get_system_info() -> dict:
    return {
        "os": platform.platform(),
        "python_version": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "load_average": _get_loadavg(),
    }


def _get_loadavg() -> dict | None:
    try:
        avg = os.getloadavg()
        return {"1min": avg[0], "5min": avg[1], "15min": avg[2]}
    except (AttributeError, OSError):
        return None


@debug_tool("get_disk_usage", "Get disk usage for current working directory")
def get_disk_usage() -> dict:
    stat = os.statvfs(".")
    total = stat.f_blocks * stat.f_frsize
    free = stat.f_bavail * stat.f_frsize
    return {
        "total_gb": round(total / 1024**3, 2),
        "free_gb": round(free / 1024**3, 2),
        "used_pct": round((1 - free / total) * 100, 1),
    }


@debug_tool("get_python_path", "Get Python module search paths")
def get_python_path() -> dict:
    return {
        "paths": sys.path,
        "count": len(sys.path),
        "site_packages": [p for p in sys.path if "site-packages" in p],
    }

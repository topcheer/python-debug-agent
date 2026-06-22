"""File descriptor inspector: open FD count, limits, and per-FD details."""

from __future__ import annotations

import os
import sys
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _list_fds() -> list[int]:
    """Return a list of open file descriptor numbers for the current process."""
    # Linux: /proc/self/fd is fast and reliable.
    if os.path.isdir("/proc/self/fd"):
        fds = []
        try:
            for name in os.listdir("/proc/self/fd"):
                try:
                    fds.append(int(name))
                except ValueError:
                    continue
            return sorted(fds)
        except OSError:
            pass

    # Fallback for non-Linux: iterate 0..soft_limit and check with os.fstat.
    try:
        import resource

        soft_limit, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        max_check = min(soft_limit, 4096)
    except (ImportError, OSError):
        max_check = 1024

    fds = []
    for fd in range(max_check):
        try:
            os.fstat(fd)
            fds.append(fd)
        except OSError:
            continue
    return sorted(fds)


def _fd_path(fd: int) -> str | None:
    """Try to resolve the path backing an fd."""
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except (OSError, AttributeError):
        pass
    # macOS / BSD: try /dev/fd
    try:
        return os.readlink(f"/dev/fd/{fd}")
    except (OSError, AttributeError):
        return None


def _fd_type(fd: int) -> str:
    """Best-effort classification of what an fd points to."""
    try:
        st = os.fstat(fd)
    except OSError:
        return "unknown"

    import stat

    mode = st.st_mode
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISCHR(mode):
        return "char_device"
    if stat.S_ISBLK(mode):
        return "block_device"
    if stat.S_ISFIFO(mode):
        return "pipe"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"


# ─── Tools ───────────────────────────────────────────────────────────────────


@debug_tool(
    "get_fd_count",
    "Count open file descriptors (Linux: /proc/self/fd, macOS/BSD: fstat scan)",
)
def get_fd_count() -> dict:
    try:
        fds = _list_fds()
        return {"open_fds": len(fds), "platform": sys.platform}
    except Exception as exc:
        return {"error": str(exc)}


@debug_tool(
    "get_fd_limit",
    "Get soft/hard RLIMIT_NOFILE limits for the process",
)
def get_fd_limit() -> dict:
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        return {
            "soft_limit": soft,
            "hard_limit": hard,
            "resource": "RLIMIT_NOFILE",
        }
    except ImportError:
        return {"error": "resource module not available on this platform"}
    except Exception as exc:
        return {"error": str(exc)}


@debug_tool(
    "get_fd_list",
    "List open file descriptors with details (fd number, type, path if available)",
)
def get_fd_list() -> dict:
    try:
        fds = _list_fds()
    except Exception as exc:
        return {"error": str(exc)}

    entries: list[dict[str, Any]] = []
    for fd in fds:
        entry: dict[str, Any] = {"fd": fd}
        try:
            entry["type"] = _fd_type(fd)
        except Exception:
            entry["type"] = "unknown"
        path = _fd_path(fd)
        if path:
            entry["path"] = path
        entries.append(entry)

    return {
        "count": len(entries),
        "platform": sys.platform,
        "descriptors": entries,
    }

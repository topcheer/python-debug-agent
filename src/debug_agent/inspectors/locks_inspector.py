"""Locks inspector: deadlock detection and lock contention analysis.

Register locks at runtime so the inspector can track them:

    from debug_agent.inspectors.locks_inspector import register_lock
    register_lock("order_lock", my_threading_lock)

Analyses ``threading.Lock`` / ``threading.RLock`` contention and detects
deadlock cycles using thread frame inspection combined with registered lock
ownership metadata.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration ──────────────────────────────────────────────────────────────

_registered_locks: dict[str, Any] = {}

# Metadata tracked per registered lock for wait-count and ownership.
#   key   -> lock object id()  (so identical locks registered under
#           multiple names share metadata)
_lock_meta: dict[int, dict[str, Any]] = {}


def register_lock(name: str, lock: Any) -> None:
    """Register a lock (threading.Lock / RLock / custom) under *name*."""
    _registered_locks[name] = lock
    key = id(lock)
    if key not in _lock_meta:
        _lock_meta[key] = {
            "names": [],
            "wait_count": 0,
            "acquire_count": 0,
            "last_owner": None,
            "last_acquired_at": None,
        }
    if name not in _lock_meta[key]["names"]:
        _lock_meta[key]["names"].append(name)


def record_lock_acquire(lock: Any, owner: str | None = None) -> None:
    """Record that *lock* was acquired (call from instrumented acquire paths)."""
    meta = _lock_meta.get(id(lock))
    if meta is None:
        return
    meta["acquire_count"] += 1
    meta["last_owner"] = owner or threading.current_thread().name
    meta["last_acquired_at"] = time.time()


def record_lock_wait(lock: Any) -> None:
    """Record that a thread started waiting on *lock*."""
    meta = _lock_meta.get(id(lock))
    if meta is None:
        return
    meta["wait_count"] += 1


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _lock_is_locked(lock: Any) -> bool:
    """Best-effort non-blocking check whether *lock* is currently held."""
    try:
        if lock.acquire(blocking=False):
            lock.release()
            return False
        return True
    except Exception:
        # RLock held by the current thread can be acquired again, so a
        # successful acquire may still mean it is locked by us.
        return False


def _get_waiter_threads() -> dict[int, str]:
    """Map thread-ident -> thread name for all live threads."""
    return {t.ident: t.name for t in threading.enumerate()}


def _thread_state(tid: int) -> str | None:
    """Return a short label for what *tid* is currently doing in its top frame."""
    frames = sys._current_frames()
    frame = frames.get(tid)
    if frame is None:
        return None
    code = frame.f_code
    func = code.co_name
    if func in ("_bootstrap", "_bootstrap_inner", "run"):
        return None
    return f"{func} ({code.co_filename}:{frame.f_lineno})"


def _find_lock_name(lock: Any) -> str | None:
    """Resolve a registered lock object back to one of its names."""
    meta = _lock_meta.get(id(lock))
    if meta and meta["names"]:
        return meta["names"][0]
    for name, obj in _registered_locks.items():
        if obj is lock:
            return name
    return None


def _detect_waiting_threads() -> dict[str, list[str]]:
    """Heuristic: which threads are blocked waiting on a lock.

    Walks every live thread's current frame chain looking for
    ``acquire`` / ``lock`` frames, then maps the lock to a registered name
    when possible.
    """
    frames = sys._current_frames()
    thread_names = _get_waiter_threads()
    waiting: dict[str, list[str]] = {}

    for tid, name in thread_names.items():
        frame = frames.get(tid)
        if frame is None:
            continue
        f = frame
        depth = 0
        while f and depth < 20:
            func = f.f_code.co_name
            if func in ("acquire", "_acquire", "wait", "lock"):
                # If a local named 'lock' / 'self' exists, try to resolve it
                lock_name = None
                for var in ("lock", "self", "mutex", "_lock"):
                    obj = f.f_locals.get(var)
                    if obj is not None:
                        lock_name = _find_lock_name(obj)
                        if lock_name:
                            break
                key = lock_name or func
                waiting.setdefault(key, []).append(name)
                break
            f = f.f_back
            depth += 1

    return waiting


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "get_lock_contention",
    "Analyze threading.Lock/RLock contention: which threads wait on which locks",
)
def get_lock_contention() -> dict:
    if not _registered_locks:
        return {
            "registered_locks": 0,
            "waiting_threads": {},
            "message": (
                "No locks registered. Use register_lock(name, lock) to track them."
            ),
        }

    waiting = _detect_waiting_threads()

    lock_states: list[dict[str, Any]] = []
    for name, lock in _registered_locks.items():
        meta = _lock_meta.get(id(lock), {})
        lock_states.append({
            "name": name,
            "locked": _lock_is_locked(lock),
            "wait_count": meta.get("wait_count", 0),
            "acquire_count": meta.get("acquire_count", 0),
            "last_owner": meta.get("last_owner"),
            "last_acquired_at": meta.get("last_acquired_at"),
        })

    return {
        "registered_locks": len(_registered_locks),
        "locks": lock_states,
        "waiting_threads": waiting,
        "total_threads": threading.active_count(),
    }


@debug_tool(
    "detect_deadlock",
    "Detect deadlock cycles using thread state and lock ownership; returns the circular dependency chain",
)
def detect_deadlock() -> dict:
    frames = sys._current_frames()
    thread_names = _get_waiter_threads()

    # Build a graph: thread T is waiting on lock L.
    # We infer L from the frame chain when the local can be resolved to a
    # registered lock.  We infer ownership from lock metadata / held state.
    thread_waits_for: dict[str, str | None] = {}  # thread name -> lock name
    lock_owner: dict[str, str | None] = {}        # lock name -> owner thread

    for tid, name in thread_names.items():
        frame = frames.get(tid)
        if frame is None:
            continue
        f = frame
        depth = 0
        while f and depth < 20:
            func = f.f_code.co_name
            if func in ("acquire", "_acquire", "lock"):
                lock_name = None
                for var in ("lock", "self", "mutex", "_lock"):
                    obj = f.f_locals.get(var)
                    if obj is not None:
                        lock_name = _find_lock_name(obj)
                        if lock_name:
                            break
                if lock_name:
                    thread_waits_for[name] = lock_name
                break
            f = f.f_back
            depth += 1

    # Resolve current owners of registered locks.
    for lock_name, lock in _registered_locks.items():
        meta = _lock_meta.get(id(lock), {})
        owner = meta.get("last_owner")
        if _lock_is_locked(lock) and owner:
            lock_owner[lock_name] = owner
        elif not _lock_is_locked(lock):
            lock_owner[lock_name] = None

    # Detect a cycle: T1 waits-on L1 owned-by T2 waits-on L2 owned-by T1 ...
    def _trace(start_thread: str) -> list[str] | None:
        chain: list[str] = [start_thread]
        current = start_thread
        seen: set[str] = {start_thread}
        while True:
            lock_name = thread_waits_for.get(current)
            if lock_name is None:
                return None
            owner = lock_owner.get(lock_name)
            if owner is None:
                return None
            chain.append(f"-> waits on lock '{lock_name}'")
            chain.append(f"-> owned by thread '{owner}'")
            if owner == start_thread:
                chain.append("-> CYCLE DETECTED (back to start)")
                return chain
            if owner in seen:
                # Cycle that doesn't involve start_thread
                chain.append(f"-> CYCLE DETECTED (thread '{owner}' revisited)")
                return chain
            seen.add(owner)
            current = owner

    cycles: list[list[str]] = []
    for thread_name in thread_waits_for:
        result = _trace(thread_name)
        if result is not None:
            cycles.append(result)

    # Deduplicate cycles by content
    unique_cycles: list[list[str]] = []
    for c in cycles:
        if c not in unique_cycles:
            unique_cycles.append(c)

    return {
        "deadlock_detected": len(unique_cycles) > 0,
        "cycle_count": len(unique_cycles),
        "cycles": unique_cycles,
        "threads_waiting": thread_waits_for,
        "lock_ownership": lock_owner,
    }


@debug_tool(
    "get_thread_locks",
    "List all registered locks with state (locked/unlocked, owner, wait count)",
)
def get_thread_locks() -> dict:
    if not _registered_locks:
        return {
            "count": 0,
            "locks": [],
            "message": "No locks registered. Use register_lock(name, lock).",
        }

    locks: list[dict[str, Any]] = []
    for name, lock in _registered_locks.items():
        meta = _lock_meta.get(id(lock), {})
        locked = _lock_is_locked(lock)
        locks.append({
            "name": name,
            "type": type(lock).__name__,
            "locked": locked,
            "owner_thread": meta.get("last_owner") if locked else None,
            "wait_count": meta.get("wait_count", 0),
            "acquire_count": meta.get("acquire_count", 0),
            "last_acquired_at": meta.get("last_acquired_at"),
        })

    return {
        "count": len(locks),
        "locks": locks,
    }

"""Counters for the deferred sync pass (interop contract v2.1, R5): how many
passes ran and how many writes they made, so a test (and a cross-add-on
re-entry test) can count them. With `TRACE` on, every write also records its
call site ("file:function:line") in `STATS["sites"]`, so a pass that keeps
writing names the writer. No bpy: importable from every module."""
import sys

STATS = {"passes": 0, "writes": 0, "last_writes": 0, "sites": []}
TRACE = False  # set True (or the environment variable WH_TRACE_WRITES=1) to record call sites


def note_write(n: int = 1) -> None:
    """One write the add-on made (an ID property, a modifier input, a build, a collection link)."""
    STATS["writes"] += n
    if TRACE:
        try:
            frame = sys._getframe(1)
            site = f"{frame.f_code.co_filename.rsplit('/', 1)[-1]}:{frame.f_code.co_name}:{frame.f_lineno}"
            caller = frame.f_back
            if caller is not None:
                site += f" <- {caller.f_code.co_name}:{caller.f_lineno}"
            STATS["sites"].append(site)
        except Exception:
            pass


def reset() -> None:
    STATS.update(passes=0, writes=0, last_writes=0)
    STATS["sites"].clear()


def _env_trace() -> bool:
    import os

    return os.environ.get("WH_TRACE_WRITES", "") not in ("", "0")


TRACE = _env_trace()

"""Opt-in, context-local stage timing. No business payloads or exception text.

Completed records are buffered and flushed once per trace, without fsync.
Failures of diagnostic output never change the wrapped operation's result.
"""
from __future__ import annotations

import contextvars
import functools
import inspect
import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_trace = contextvars.ContextVar("brain_perf_trace", default=None)
_parent = contextvars.ContextVar("brain_perf_parent", default=None)
_TAGS = frozenset({
    "stage", "kind", "requests", "cache_hit", "file_count", "total_bytes",
    "http_request_id", "http_status", "prompt_tokens", "completion_tokens",
    "total_tokens", "prompt_chars", "prompt_bytes", "response_chars",
    "request_body_bytes", "planner_context_chars", "retry_index", "retry_count",
    "retry_reason", "finish_reason", "skill_prompt_source", "skill_md_sha256",
    "skill_prompt_chars", "skill_prompt_bytes", "prompt_sha256", "step_index",
    "attempt", "task_id", "executed", "error_type", "wait_kind", "planner",
    "response_format", "status", "qwen_http_wait_ms",
})


def enabled():
    return os.getenv("ROBOT_BRAIN_PERF_TRACE", "0") == "1"


def _safe_tags(values):
    # Explicit allowlist: no prompts, instruction text, credentials, URLs,
    # paths, scene documents or exception messages are accepted.
    result = {}
    for key, value in values.items():
        if key not in _TAGS or not isinstance(value, (str, int, float, bool, type(None))):
            continue
        if isinstance(value, str):
            if len(value) > 256 or "/" in value or "\\" in value:
                continue
        result[key] = value
    return result


class PerfTrace:
    def __init__(self, trace_id=None, output_dir=None):
        # Never use caller-controlled IDs as filesystem paths.
        self.trace_id = trace_id or uuid.uuid4().hex
        self.output_dir = output_dir
        self.records = []
        self.lock = threading.Lock()
        self.output_error = None
        self.path = None
        self.deferred = False

    def append(self, record):
        with self.lock:
            self.records.append(record)

    def flush(self):
        try:
            root = Path(self.output_dir or os.getenv("PERF_TRACE_OUTPUT_DIR", "var/perf"))
            safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(self.trace_id))[:80]
            directory = root / (safe_id + "-" + uuid.uuid4().hex)
            directory.mkdir(parents=True, exist_ok=False)
            self.path = directory / "spans.jsonl"
            with self.lock, self.path.open("x", encoding="utf-8") as stream:
                for record in self.records:
                    stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        except Exception as exc:
            self.output_error = type(exc).__name__


class Span:
    def __init__(self, trace, name, component, source, tags):
        self.trace, self.tags = trace, _safe_tags(tags)
        self.record = dict(type="span", trace_id=trace.trace_id,
                           span_id=uuid.uuid4().hex, parent_span_id=_parent.get(),
                           name=name, component=component, source=source,
                           pid=os.getpid(), thread_id=threading.get_ident())

    def annotate(self, **tags):
        self.tags.update(_safe_tags(tags))


@contextmanager
def span(name, *, component="brain", source="", **tags):
    trace = _trace.get()
    if trace is None:
        yield None
        return
    item = Span(trace, name, component, source, tags)
    token = _parent.set(item.record["span_id"])
    item.record.update(start_ns=time.perf_counter_ns(),
                       start_wall=datetime.now(timezone.utc).isoformat(), status="ok")
    try:
        yield item
    except BaseException as exc:
        item.record["status"] = "error"
        item.annotate(error_type=type(exc).__name__)
        raise
    finally:
        end = time.perf_counter_ns()
        item.record.update(end_ns=end, end_wall=datetime.now(timezone.utc).isoformat(),
                           duration_ms=(end-item.record["start_ns"])/1e6, tags=item.tags)
        _parent.reset(token)
        trace.append(item.record)


@contextmanager
def trace_scope(trace_id=None, *, output_dir=None):
    if not enabled():
        yield None
        return
    if _trace.get() is not None:
        yield _trace.get()
        return
    trace = PerfTrace(trace_id, output_dir)
    token = _trace.set(trace)
    parent_token = _parent.set(None)
    try:
        yield trace
    finally:
        _parent.reset(parent_token)
        _trace.reset(token)
        if not trace.deferred:
            trace.flush()


def current_trace():
    return _trace.get()


def stamp():
    return time.perf_counter_ns(), datetime.now(timezone.utc).isoformat()


def interval(trace, name, started, *, source, **tags):
    """Record a queued interval whose start crossed an async task boundary."""
    if trace is None:
        return
    end, wall = stamp()
    trace.append(dict(type="span", trace_id=trace.trace_id, span_id=uuid.uuid4().hex,
                      parent_span_id=None, name=name, component="brain.web", source=source,
                      start_ns=started[0], end_ns=end, duration_ms=(end-started[0])/1e6,
                      start_wall=started[1], end_wall=wall, status="ok",
                      pid=os.getpid(), thread_id=threading.get_ident(), tags=_safe_tags(tags)))


@contextmanager
def attached_trace(trace):
    token, parent = _trace.set(trace), _parent.set(None)
    try:
        yield trace
    finally:
        _parent.reset(parent)
        _trace.reset(token)


def timed(name, *, component="brain"):
    """Preserve sync/async signatures and exceptions; opt-in root is explicit."""
    def decorate(function):
        filename = inspect.getsourcefile(function) or ""
        marker = "robot_agent_brain/"
        source = (marker + filename.split(marker, 1)[1] if marker in filename
                  else Path(filename).name) + ":" + function.__qualname__
        if inspect.iscoroutinefunction(function):
            @functools.wraps(function)
            async def asynchronous(*args, **kwargs):
                if _trace.get() is None:
                    return await function(*args, **kwargs)
                with span(name, component=component, source=source):
                    return await function(*args, **kwargs)
            return asynchronous
        @functools.wraps(function)
        def synchronous(*args, **kwargs):
            if _trace.get() is None:
                return function(*args, **kwargs)
            with span(name, component=component, source=source):
                return function(*args, **kwargs)
        return synchronous
    return decorate

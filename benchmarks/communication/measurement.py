"""Measurement contract shared by the Python endpoints and matrix runner."""

import csv
import json
import math
from pathlib import Path
import time


FIELDS = ("sequence", "scheduled_ns", "start_ns", "end_ns", "ok", "missed_before")
PREFLIGHT_ATTEMPTS = 3


def write_json(path, payload):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def wait_file(path, timeout=120.0):
    deadline = time.monotonic() + timeout
    while not Path(path).exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for {path}")
        time.sleep(0.002)


def window(config, exchange, duration, *, record, sequence_start):
    """Paced closed loop with at most one outstanding exchange; no catch-up burst."""
    period = max(1, round(1e9 / config["rate_hz"]))
    begin = time.monotonic_ns()
    finish = begin + round(duration * 1e9)
    due = begin
    rows = []
    sequence = sequence_start
    while due < finish:
        now = time.monotonic_ns()
        if now < due:
            time.sleep((due - now) / 1e9)
            now = time.monotonic_ns()
        if now >= finish:
            break
        missed = (now - due) // period
        due += missed * period
        start = time.monotonic_ns()
        ok = exchange(sequence)
        end = time.monotonic_ns()
        if record:
            rows.append((sequence, due, start, end, int(ok), missed))
        sequence += 1
        due += period
    end = time.monotonic_ns()
    # Include scheduled slots that expired after the last attempted exchange.
    trailing = max(0, math.ceil((finish - due) / period))
    return rows, {"begin_ns": begin, "end_ns": end, "elapsed_s": (end - begin) / 1e9,
                  "trailing_missed": trailing, "attempts": sequence - sequence_start}


def measure(config, exchange, serialized_bytes, *, full_validation, metadata=None):
    # Best-effort ROS endpoints can drop their first packet immediately after
    # discovery. This validation is outside the measurement window, so retry
    # it without hiding losses recorded by the actual workload.
    preflight_success = any(full_validation() for _ in range(PREFLIGHT_ATTEMPTS))
    # A sensor stream is allowed to lose every sample. Continue so that the
    # measured result reports that loss instead of classifying it as a process
    # setup failure. Validation errors still raise from full_validation().
    if not preflight_success and config.get("ros_qos") != "sensor":
        raise RuntimeError("Preflight payload validation failed")
    _, warmup = window(config, exchange, config["warmup_s"], record=False, sequence_start=1)
    directory = Path(config["directory"])
    write_json(directory / "ready.json", dict(
        metadata or {}, serialized_message_bytes=serialized_bytes,
        preflight_success=preflight_success))
    wait_file(directory / "go")
    rows, timing = window(config, exchange, config["duration_s"], record=True,
                          sequence_start=warmup["attempts"] + 1)
    write_json(directory / "done.json", timing)
    # Keep the endpoints alive for the final process-tree CPU snapshot. Export
    # raw samples only afterward so disk IO is outside both measurement windows.
    wait_file(directory / "release")
    with (directory / "samples.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(FIELDS)
        writer.writerows(rows)

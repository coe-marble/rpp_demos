"""Summarize raw samples without hiding failures or averaging worst times."""

import argparse
import csv
import html
import json
import math
from pathlib import Path

from measurement import write_json


def percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    return sorted_values[max(0, math.ceil(len(sorted_values) * fraction) - 1)]


def distribution(values):
    values.sort()
    mean = math.fsum(values) / len(values) if values else None
    squared_deviations = math.fsum((value - mean) ** 2 for value in values)
    return {"samples": len(values), "min_us": values[0] if values else None,
            "mean_us": mean,
            "stddev_us": math.sqrt(squared_deviations / (len(values) - 1)) if len(values) > 1 else None,
            "p50_us": percentile(values, 0.5), "p95_us": percentile(values, 0.95),
            "p99_us": percentile(values, 0.99), "p999_us": percentile(values, 0.999),
            "max_us": values[-1] if values else None}


def summarize(directory):
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    timing = json.loads((directory / "done.json").read_text(encoding="utf-8"))
    ready = json.loads((directory / "ready.json").read_text(encoding="utf-8"))
    cpu = json.loads((directory / "cpu.json").read_text(encoding="utf-8"))
    cpu["process_count"] = len(cpu["processes"]) if cpu["complete"] else None
    elapsed = timing["elapsed_s"]
    latencies, scheduled_latencies, latenesses = [], [], []
    misses = timing["trailing_missed"]
    attempts = 0
    timeouts = 0
    with (directory / "samples.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            attempts += 1
            misses += int(row["missed_before"])
            if int(row["ok"]) == 0:
                timeouts += 1
                continue
            latencies.append((int(row["end_ns"]) - int(row["start_ns"])) / 1000)
            scheduled_latencies.append((int(row["end_ns"]) - int(row["scheduled_ns"])) / 1000)
            latenesses.append((int(row["start_ns"]) - int(row["scheduled_ns"])) / 1000)
    successful = len(latencies)
    if attempts != timing["attempts"]:
        raise ValueError(f"Incomplete sample export in {directory}")
    result = {
        "case": config["case"], "backend": config["backend"], "profile": config["profile"],
        "repeat": config["repeat"], "sender": config["sender"], "receiver": config["receiver"],
        "placement": config["placement"], "payload_bytes": config["payload_bytes"],
        "serialized_message_bytes": ready["serialized_message_bytes"], "endpoint": ready,
        "requested_rate_hz": config["rate_hz"],
        "offered_hz": config["rate_hz"], "elapsed_s": elapsed, "attempts": attempts,
        "successful": successful, "reply_timeouts": timeouts, "missed_schedule_slots": misses,
        "achieved_hz": successful / elapsed,
        "schedule_completion_fraction": successful / (attempts + misses) if attempts + misses else 0,
        "round_trip": distribution(latencies), "scheduled_round_trip": distribution(scheduled_latencies),
        "send_lateness": distribution(latenesses),
        "application_bandwidth_Bps": successful * config["payload_bytes"] * 2 / elapsed,
        "serialized_equivalent_bandwidth_Bps": successful * ready["serialized_message_bytes"] * 2 / elapsed,
        "cpu": cpu,
        "cpu_us_per_successful_exchange": (
            cpu["cpu_s"] * 1e6 / successful
            if cpu.get("cpu_s") is not None and successful else None),
        "configuration": {key: config.get(key) for key in (
            "case", "profile", "repeat", "sender", "receiver", "placement",
            "payload_bytes", "rate_hz", "duration_s", "warmup_s", "ros_qos", "reliability",
            "qos_depth", "reply_timeout_s", "startup_timeout_s")},
    }
    write_json(directory / "summary.json", result)
    return result


def scenario_metadata(record):
    config = record.get("configuration", record)
    return {"case": config["case"], "profile": config["profile"], "repeat": config["repeat"],
            "sender": config["sender"], "receiver": config["receiver"],
            "placement": config["placement"], "payload_bytes": config["payload_bytes"],
            "requested_hz": config.get("rate_hz", record.get("offered_hz")),
            "duration_s": config.get("duration_s"), "warmup_s": config.get("warmup_s"),
            "ros_qos": config.get("ros_qos"), "reliability": config.get("reliability"),
            "qos_depth": config.get("qos_depth"),
            "reply_timeout_s": config.get("reply_timeout_s")}


RESULT_COLUMNS = ("rpp", "ros_reliable", "ros_sensor")


def pair_results(root, results):
    """Collect one RPP baseline and both ROS QoS variants for each scenario."""
    qos_keys = ("ros_qos", "reliability", "qos_depth")
    groups = {}

    def group_for(record):
        metadata = scenario_metadata(record)
        base = {key: value for key, value in metadata.items() if key not in qos_keys}
        key = tuple(base.values())
        return groups.setdefault(key, {
            "scenario": base,
            "rpp": None,
            "rpp_planned": False,
            "rpp_failure": None,
            "ros2": {},
            "ros2_planned": set(),
            "ros2_failures": {},
            "qos": {},
        })

    def register(record, result=None, error=None):
        group = group_for(record)
        metadata = scenario_metadata(record)
        backend = record["backend"]
        if backend == "rpp":
            if result is None and error is None:
                group["rpp_planned"] = True
            elif error is not None:
                group["rpp_failure"] = error
            elif group["rpp"] is not None:
                raise ValueError(f"Duplicate rpp result for {group['scenario']}")
            else:
                group["rpp"] = result
            return
        mode = metadata.get("ros_qos") or metadata.get("reliability") or "legacy"
        metadata["ros_qos"] = mode
        group["qos"][mode] = {key: metadata[key] for key in qos_keys}
        if result is None and error is None:
            group["ros2_planned"].add(mode)
        elif error is not None:
            group["ros2_failures"][mode] = error
        elif mode in group["ros2"]:
            raise ValueError(f"Duplicate ros2 {mode} result for {group['scenario']}")
        else:
            group["ros2"][mode] = result

    plan_path = root / "plan.json"
    if plan_path.exists():
        for config in json.loads(plan_path.read_text(encoding="utf-8")):
            register(config)
    for result in results:
        register(result, result=result)
    failures_path = root / "failures.json"
    failures = (json.loads(failures_path.read_text(encoding="utf-8"))
                if failures_path.exists() else [])
    # New result sets store the complete failed configuration. Older result
    # sets used display labels, which cannot be safely mapped after QoS modes
    # were added, so retain their successful samples without guessing failures.
    for failure in failures:
        if failure.get("config"):
            register(failure["config"], error=failure["error"])

    comparisons = []
    for group in groups.values():
        # Keep the in-memory set while registering plan entries, but expose
        # comparison.json as ordinary JSON data.
        group["ros2_planned"] = sorted(group["ros2_planned"])
        comparisons.append(group)
    return sorted(comparisons, key=lambda group: (
        group["scenario"]["payload_bytes"], group["scenario"]["requested_hz"],
        group["scenario"]["case"], group["scenario"]["repeat"],
        json.dumps(group["scenario"], sort_keys=True)))


def metric(result, path):
    for key in path.split("."):
        if not isinstance(result, dict):
            return None
        result = result.get(key)
    return result


def result_for(group, column):
    if column == "rpp":
        return group["rpp"]
    return group["ros2"].get(column.removeprefix("ros_"))


def is_planned(group, column):
    if column == "rpp":
        return group["rpp_planned"] or group["rpp"] is not None
    mode = column.removeprefix("ros_")
    return mode in group["ros2_planned"] or mode in group["ros2"]


def failure_for(group, column):
    if column == "rpp":
        return group["rpp_failure"]
    return group["ros2_failures"].get(column.removeprefix("ros_"))


def status(group, column):
    result = result_for(group, column)
    if failure_for(group, column) or (result is not None and not result["successful"]):
        return "FAILED"
    if result is None:
        return "NO RESULT" if is_planned(group, column) else "NOT RUN"
    return "OK" if not result["reply_timeouts"] else "TIMEOUTS"


def number(value, *, scale=1, digits=2):
    return "n/a" if value is None else f"{value * scale:,.{digits}f}"


def comparison_cells(group, path, *, lower=False, scale=1, digits=2, compare=True):
    values = [metric(result_for(group, column), path) for column in RESULT_COLUMNS]
    cells = [number(value, scale=scale, digits=digits) for value in values]
    comparable = (compare and all(value is not None for value in values)
                  and all(status(group, column) in ("OK", "TIMEOUTS") for column in RESULT_COLUMNS))
    if comparable:
        best = min(values) if lower else max(values)
        if values.count(best) == 1:
            cells[values.index(best)] = f"**{cells[values.index(best)]}**"
    return cells


def scenario_title(metadata):
    names = {"cpp": "C++", "python": "Python"}
    return f"{names[metadata['sender']]} → {names[metadata['receiver']]}"


def aggregate_scenario(groups):
    """Use summed counters for averages and retain the largest observed latency."""
    scenario = dict(groups[0]["scenario"])
    scenario.pop("repeat")
    combined = {"scenario": scenario, "rpp": None, "rpp_planned": False,
                "rpp_failure": None, "ros2": {}, "ros2_planned": set(),
                "ros2_failures": {}, "qos": groups[0]["qos"], "runs": {}}
    for column in RESULT_COLUMNS:
        expected = sum(is_planned(group, column) for group in groups)
        completed = [result_for(group, column) for group in groups
                     if status(group, column) in ("OK", "TIMEOUTS")]
        failed = sum(status(group, column) == "FAILED" for group in groups)
        combined["runs"][column] = {"completed": len(completed), "expected": expected,
                                     "failed": failed}
        if expected:
            if column == "rpp":
                combined["rpp_planned"] = True
            else:
                combined["ros2_planned"].add(column.removeprefix("ros_"))
        # Incomplete sets cannot win against a fully completed set.
        if failed or (expected and len(completed) != expected):
            if column == "rpp":
                combined["rpp_failure"] = "Incomplete repetition set"
            else:
                combined["ros2_failures"][column.removeprefix("ros_")] = "Incomplete repetition set"
        if not completed:
            continue
        successes = sum(result["successful"] for result in completed)
        elapsed = sum(result["elapsed_s"] for result in completed)
        scheduled = sum(result["attempts"] + result["missed_schedule_slots"] for result in completed)
        cpu_complete = all(result["cpu"].get("cpu_s") is not None for result in completed)
        cpu_s = sum(result["cpu"]["cpu_s"] for result in completed) if cpu_complete else None
        cpu_window = sum(result["cpu"]["sample_window_s"] for result in completed)
        mean = math.fsum(result["round_trip"]["mean_us"] * result["successful"]
                         for result in completed) / successes
        # Pool within-run and between-run variation. Averaging run SDs would
        # discard changes in the mean between runs and weight unequal runs badly.
        squared_deviations = math.fsum(
            (result["successful"] - 1) * (result["round_trip"]["stddev_us"] or 0) ** 2
            + result["successful"] * (result["round_trip"]["mean_us"] - mean) ** 2
            for result in completed)
        aggregated = {
            "successful": successes,
            "reply_timeouts": sum(result["reply_timeouts"] for result in completed),
            "achieved_hz": successes / elapsed,
            "schedule_completion_fraction": successes / scheduled if scheduled else 0,
            "application_bandwidth_Bps": sum(result["application_bandwidth_Bps"] * result["elapsed_s"]
                                               for result in completed) / elapsed,
            "round_trip": {
                "mean_us": mean,
                "stddev_us": math.sqrt(squared_deviations / (successes - 1)) if successes > 1 else None,
                "max_us": max(result["round_trip"]["max_us"] for result in completed)},
            "cpu": {"percent_one_core": cpu_s * 100 / cpu_window if cpu_complete else None},
        }
        if column == "rpp":
            combined["rpp"] = aggregated
        else:
            combined["ros2"][column.removeprefix("ros_")] = aggregated
    return combined


def compact_sections(groups):
    workloads = {}
    for group in groups:
        meta = group["scenario"]
        workload = {key: value for key, value in meta.items()
                    if key not in ("case", "sender", "receiver", "placement", "repeat")}
        key = tuple(workload.values())
        section = workloads.setdefault(key, {"metadata": workload, "scenarios": {}})
        scenario_key = (meta["placement"], meta["sender"], meta["receiver"], meta["case"])
        section["scenarios"].setdefault(scenario_key, []).append(group)
    sections = list(workloads.values())
    for section in sections:
        section["scenarios"] = [sorted(repetitions, key=lambda group: group["scenario"]["repeat"])
                                for _, repetitions in sorted(section["scenarios"].items())]
    return sections


def metric_rows(group, *, detailed=False):
    definitions = [
        ("Mean RTT ± SD · µs ↓", "round_trip.mean_us", True, 1, 2),
        ("Worst RTT · µs ↓", "round_trip.max_us", True, 1, 2),
        ("Achieved rate · Hz ↑", "achieved_hz", False, 1, 2),
        ("Completed load · % ↑", "schedule_completion_fraction", False, 100, 2),
        ("Payload bandwidth · MiB/s ↑", "application_bandwidth_Bps", False, 1 / 1048576, 2),
        ("CPU usage · % ↓", "cpu.percent_one_core", True, 1, 2),
    ]
    if detailed:
        definitions += [
            ("Median RTT · µs ↓", "round_trip.p50_us", True, 1, 2),
            ("p99 RTT · µs ↓", "round_trip.p99_us", True, 1, 2),
            ("p99.9 RTT · µs ↓", "round_trip.p999_us", True, 1, 2),
            ("Scheduled worst · µs ↓", "scheduled_round_trip.max_us", True, 1, 2),
            ("CPU per reply · µs ↓", "cpu_us_per_successful_exchange", True, 1, 2),
            ("Serialized size · B ↓", "serialized_message_bytes", True, 1, 0),
            ("OS processes", "cpu.process_count", False, 1, 0),
            ("Reply timeouts ↓", "reply_timeouts", True, 1, 0),
            ("Missed slots ↓", "missed_schedule_slots", True, 1, 0),
        ]
    rows = []
    for label, path, lower, scale, digits in definitions:
        comparable = path != "cpu.process_count"
        if path == "cpu.percent_one_core":
            rates = [metric(result_for(group, column), "achieved_hz") for column in RESULT_COLUMNS]
            comparable = all(rate is not None and rate > 0 for rate in rates)
            if comparable:
                comparable = min(rates) / max(rates) >= 0.95
        cells = comparison_cells(group, path, lower=lower, scale=scale,
                                 digits=digits, compare=comparable)
        if path == "round_trip.mean_us":
            cells = [f"{value} ± {number(metric(result_for(group, column), 'round_trip.stddev_us'))}"
                     if metric(result_for(group, column), path) is not None else value
                     for column, value in zip(RESULT_COLUMNS, cells)]
        rows.append([label] + cells)
    return rows


def workload_label(meta):
    size = (f"{meta['payload_bytes'] / 1048576:g} MiB"
            if meta["payload_bytes"] >= 1048576 and meta["payload_bytes"] % 1048576 == 0
            else f"{meta['payload_bytes']:,} B")
    rate = f"{meta['requested_hz']:g} Hz"
    return f"{size} · {rate} requested"


def run_count(group, column):
    counts = group["runs"][column]
    if not counts["expected"]:
        return "Not run"
    label = f"{counts['completed']}/{counts['expected']} completed"
    if counts["failed"]:
        label += f" · {counts['failed']} failed"
    return label


REPORT_NOTES = [
    "Requested Hz is the commanded request/echo exchange rate, not the achieved rate. "
    "Each completed exchange contains a request and full reply: each direction has that message rate; "
    "the combined message rate is twice the exchange rate. Payload B excludes the sequence field.",
    "Each table has one RPP column and both ROS QoS columns. Rows pair exactly the same languages, "
    "placement, payload, requested rate, duration, warmup, reply timeout, and repetition. "
    "Different configurations never share a comparison row.",
    "Bold marks the numerically better observed metric (arrows show direction); ties and missing/failed "
    "comparisons are not highlighted. This is not a statistical significance claim. CPU percentage is "
    "highlighted only when achieved rates differ by at most 5%. CPU µs/reply uses total endpoint CPU "
    "divided by successful replies; inspect completion and failures alongside latency.",
    "RTT uses the sender clock and includes source dispatch/publication, reply handling, and boundary "
    "validation. Worst means maximum observed successful RTT, not guaranteed worst-case time. "
    "Timeouts and skipped schedule slots are shown separately; the load generator is closed loop.",
    "One process means two RPP plugins coordinated by a script, or two ROS nodes in one executor. "
    "Separate processes means two real OS processes on the same host: an RPP worker and child component "
    "server, or separate ROS sender/responder workers. A subprocess is itself a separate process.",
    "This is an end-to-end architecture comparison: native RPP dispatches directly; native C++ ROS "
    "uses rclcpp intra-process delivery, and native Python ROS uses rclpy/RMW. Across processes RPP "
    "uses Cap'n Proto RPC over loopback TCP; ROS uses its selected RMW, possibly shared memory. "
    "These results do not isolate Cap'n Proto serialization versus CDR or enforce identical transports.",
    "Payload MiB/s sums successful request and reply payloads. Serialized B measures one standalone "
    "message and excludes RPC/DDS/network overhead; it is not wire traffic. CPU 100% is one core "
    "across both endpoint process trees, excluding the runner and external middleware daemons.",
]


def write_comparison_report(root, groups):
    sections = compact_sections(groups)
    lines = ["# RPP and ROS communication comparison", "",
             "Grouped by commanded workload, then scenario. Bold marks the better observed result.", "",
             "Summary averages use all completed runs; worst RTT is the largest observation across runs. "
             "Incomplete repetition sets receive no winner highlighting. Open report.html for the compact card layout.", ""]
    page = ["<!doctype html><html lang='en'><meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            "<title>RPP and ROS communication comparison</title>",
            "<style>body{font:14px system-ui,sans-serif;margin:0;background:#f5f7fb;color:#182339}"
            "main{max-width:1100px;margin:auto;padding:28px 20px}h1{font-size:26px;margin:0 0 8px}"
            "h2{font-size:22px;margin:0 0 6px}h3{font-size:17px;margin:0}p{line-height:1.55}"
            ".intro,.meta,.placement{color:#536078}.workload{margin-top:32px}.grid{display:grid;"
            "grid-template-columns:repeat(auto-fit,minmax(min(100%,430px),1fr));gap:16px;margin-top:16px}"
            ".card{background:white;border:1px solid #dce3ed;border-radius:12px;padding:18px;min-width:0}"
            ".placement{margin:3px 0 14px;font-size:13px}table{width:100%;border-collapse:collapse;table-layout:fixed}"
            "th,td{padding:8px 6px;text-align:right;border-bottom:1px solid #edf0f5;"
            "font-variant-numeric:tabular-nums;overflow-wrap:anywhere}th:first-child,td:first-child{text-align:left;width:46%}"
            "th{font-size:12px;color:#536078}.rpp{color:#2458a4}.ros{color:#17684d}"
            "strong{font-weight:750;color:#146643}.runs{font-size:12px;color:#536078}"
            "details{margin-top:12px}summary{cursor:pointer;color:#37527c;padding:6px 0}"
            ".repeat{border-top:1px solid #dce3ed;padding-top:12px;margin-top:12px}"
            ".repeat h4{margin:0 0 6px}.error{color:#a52828;font-size:12px;overflow-wrap:anywhere}"
            ".notes{margin-top:24px}.notes p{max-width:900px}.metadata{font-size:13px;color:#536078}"
            "nav{display:flex;gap:10px;flex-wrap:wrap;margin:20px 0}nav a{color:#2458a4;background:#e8effa;"
            "padding:8px 12px;border-radius:8px;text-decoration:none}.run-cell{font-size:12px}"
            "</style><main><h1>RPP and ROS communication</h1>",
            "<p class='intro'>One workload at a time. RPP, ROS reliable, and ROS sensor are side by side. "
            "Bold marks the better observed result; expand a card for individual runs and metadata.</p>",
            "<nav>"]
    for index, section in enumerate(sections):
        page.append(f"<a href='#workload-{index}'>{html.escape(workload_label(section['metadata']))}</a>")
    page.append("</nav>")

    def escaped_cell(value):
        return "".join("<strong>" + html.escape(part) + "</strong>" if index % 2 else html.escape(part)
                       for index, part in enumerate(value.split("**")))

    def html_table(rows):
        parts = ["<table><thead><tr><th>Metric</th><th class='rpp'>RPP</th>"
                 "<th class='ros'>ROS reliable</th><th class='ros'>ROS sensor</th>"
                 "</tr></thead><tbody>"]
        for row in rows:
            parts.append("<tr>" + "".join(f"<td>{escaped_cell(value)}</td>" for value in row) + "</tr>")
        parts.append("</tbody></table>")
        return "\n".join(parts)

    def markdown_table(rows):
        return ["| Metric | RPP | ROS reliable | ROS sensor |", "| --- | ---: | ---: | ---: |", *[
            "| " + " | ".join(value.replace("|", "\\|").replace("\n", " ") for value in row) + " |"
            for row in rows], ""]

    for index, section in enumerate(sections):
        meta = section["metadata"]
        title = workload_label(meta)
        timing = f"{number(meta['duration_s'])} s measurement · {number(meta['warmup_s'])} s warmup per run"
        lines.extend([f"## {title}", "", timing, ""])
        page.extend([f"<section class='workload' id='workload-{index}'><h2>{html.escape(title)}</h2>",
                     f"<p class='meta'>{html.escape(timing)}</p><div class='grid'>"])
        for repetitions in section["scenarios"]:
            group = aggregate_scenario(repetitions)
            scenario = group["scenario"]
            title = scenario_title(scenario)
            placement = "One process" if scenario["placement"] == "native" else "Two separate processes · same host"
            rows = [["Runs completed", *(run_count(group, column) for column in RESULT_COLUMNS)]] + metric_rows(group)
            lines.extend([f"### {title} — {placement}", "", *markdown_table(rows),
                          "<details>", "<summary>Individual runs and metadata</summary>", ""])
            page.extend([f"<article class='card'><h3>{html.escape(title)}</h3>",
                         f"<p class='placement'>{html.escape(placement)}</p>", html_table(rows),
                         "<details><summary>Individual runs and metadata</summary>"])
            reliable = group["qos"].get("reliable", {})
            sensor = group["qos"].get("sensor", {})
            metadata = (f"Profile: {meta['profile']}; payload: {meta['payload_bytes']:,} B; "
                        f"requested rate: {meta['requested_hz']:g} exchanges/s; "
                        f"ROS reliable ({reliable.get('reliability', 'n/a')}, volatile, "
                        f"depth {reliable.get('qos_depth', 'n/a')}); ROS sensor "
                        f"({sensor.get('reliability', 'n/a')}, volatile, "
                        f"depth {sensor.get('qos_depth', 'n/a')}); "
                        f"ROS reply timeout: {number(meta['reply_timeout_s'])} s.")
            lines.extend([metadata, ""])
            page.append(f"<p class='metadata'>{html.escape(metadata)}</p>")
            for repeat in repetitions:
                repeat_title = f"Run {repeat['scenario']['repeat']}"
                detailed = [["Status", *(status(repeat, column) for column in RESULT_COLUMNS)]] + metric_rows(repeat, detailed=True)
                lines.extend([f"#### {repeat_title}", "", *markdown_table(detailed)])
                page.extend([f"<div class='repeat'><h4>{html.escape(repeat_title)}</h4>", html_table(detailed)])
                for column in RESULT_COLUMNS:
                    error = failure_for(repeat, column)
                    if not error:
                        continue
                    message = f"{column.replace('_', ' ').upper()}: {error}"
                    lines.extend([message, ""])
                    page.append(f"<p class='error'>{html.escape(message)}</p>")
                page.append("</div>")
            lines.extend(["</details>", ""])
            page.append("</details></article>")
        page.append("</div></section>")
    notes = [
        "Mean RTT ± SD shows the mean and sample standard deviation in microseconds (n−1 denominator), "
        "not a confidence interval or standard error. The summary pools individual observations across "
        "completed runs, including between-run variation; it does not average run SDs. SD is unavailable "
        "with fewer than two observations. Highlighting on this row compares means only.",
        "Summary mean RTT is weighted by the number of successful exchanges. Achieved rate and payload "
        "bandwidth use total successful work divided by total measured time. CPU percentage uses total "
        "CPU divided by total CPU sampling time. Worst RTT is the maximum across completed runs; it is never averaged.",
        "Failed or missing runs are counted in each card. Statistics use completed runs only; a scenario "
        "with an incomplete repetition set receives no winner highlighting. Expand individual runs for failures, "
        "tail percentiles, serialized sizes, observed process counts, and missed schedule slots.",
        *REPORT_NOTES[:1], *REPORT_NOTES[2:],
    ]
    lines.extend(["## Measurement and comparison limits", ""])
    page.append("<details class='notes'><summary>Measurement definitions and comparison limits</summary>")
    for note in notes:
        lines.extend([note, ""])
        page.append(f"<p>{html.escape(note)}</p>")
    page.append("</details></main></html>")
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (root / "report.html").write_text("\n".join(page), encoding="utf-8")


def write_report(root, results):
    write_json(root / "summary.json", results)
    fields = ["backend", "case", "profile", "repeat", "payload_bytes", "serialized_message_bytes",
              "requested_rate_hz",
              "offered_hz", "achieved_hz", "reply_timeouts", "missed_schedule_slots",
              "mean_us", "stddev_us", "p50_us", "p99_us", "p999_us", "max_us", "scheduled_max_us",
              "application_bandwidth_Bps", "serialized_equivalent_bandwidth_Bps", "cpu_pct_one_core",
              "duration_s", "warmup_s", "ros_qos", "reliability", "qos_depth",
              "cpu_us_per_successful_exchange"]
    with (root / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in results:
            row = {key: result.get(key) for key in fields}
            row.update({key: result["round_trip"][key]
                        for key in ("mean_us", "stddev_us", "p50_us", "p99_us", "p999_us", "max_us")})
            row["scheduled_max_us"] = result["scheduled_round_trip"]["max_us"]
            row["cpu_pct_one_core"] = result["cpu"]["percent_one_core"]
            row.update({key: result.get("configuration", {}).get(key)
                        for key in ("duration_s", "warmup_s", "ros_qos", "reliability", "qos_depth")})
            writer.writerow(row)
    groups = pair_results(root, results)
    write_json(root / "comparison.json", groups)
    write_comparison_report(root, groups)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    if not args.results.is_dir():
        parser.error(f"Results directory does not exist: {args.results}")
    samples = sorted(args.results.glob("*/samples.csv"))
    if not samples:
        parser.error(f"No exported samples found in {args.results}")
    results = [summarize(path.parent) for path in samples]
    write_report(args.results, results)


if __name__ == "__main__":
    main()

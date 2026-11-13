"""Run the matched RPP/ROS matrix. Never builds, registers, or installs software."""

import argparse
from contextlib import ExitStack
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import signal
import subprocess
import sys
import time
import uuid

from measurement import PREFLIGHT_ATTEMPTS, write_json
from report import summarize, write_report


ROOT = Path(__file__).resolve().parent
CASES = {
    "cpp_native": ("cpp", "cpp", "native"),
    "python_native": ("python", "python", "native"),
    "cpp_subprocess": ("cpp", "cpp", "subprocess"),
    "python_subprocess": ("python", "python", "subprocess"),
    "cpp_to_python": ("cpp", "python", "subprocess"),
    "python_to_cpp": ("python", "cpp", "subprocess"),
}

# ``sensor`` matches ROS SensorDataQoS: volatile, best-effort, keep-last five.
ROS_QOS_MODES = {
    "reliable": {"reliability": "reliable", "qos_depth": 64},
    "sensor": {"reliability": "best_effort", "qos_depth": 5},
}


def proc_tree(roots):
    """Enumerate children from every thread, including RPP's RPC executor."""
    pending = list(roots)
    seen = set()
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        for path in Path(f"/proc/{pid}/task").glob("*/children"):
            try:
                pending.extend(int(child) for child in path.read_text().split())
            except (FileNotFoundError, ProcessLookupError):
                continue
    return seen


def cpu_snapshot(roots):
    snapshot = {}
    for pid in proc_tree(roots):
        try:
            text = Path(f"/proc/{pid}/stat").read_text()
            fields = text[text.rfind(")") + 2:].split()
            # Remaining fields start at Linux stat field 3 (state).
            snapshot[(pid, int(fields[19]))] = {
                "ticks": int(fields[11]) + int(fields[12]),
                "parent_pid": int(fields[1]),
                "command": text[text.find("(") + 1:text.rfind(")")],
            }
        except (FileNotFoundError, ProcessLookupError):
            continue
    return snapshot


def cpu_delta(before, after, elapsed):
    complete = before.keys() == after.keys()
    ticks_per_second = os.sysconf("SC_CLK_TCK")
    processes = [{"pid": pid, "command": after[(pid, start)]["command"],
                  "parent_pid": after[(pid, start)]["parent_pid"],
                  "cpu_s": (after[(pid, start)]["ticks"] - before[(pid, start)]["ticks"]) / ticks_per_second}
                 for pid, start in sorted(before.keys() & after.keys())]
    total = sum(process["cpu_s"] for process in processes)
    return {"complete": complete, "processes": processes,
            "process_count": len(processes) if complete else None,
            "cpu_s": total if complete else None,
            "sample_window_s": elapsed, "percent_one_core": total * 100 / elapsed if complete else None,
            "resolution_s": 1 / ticks_per_second,
            "note": "Endpoint process tree changed during measurement" if not complete else ""}


def stop(process):
    # Each root owns a process group, including any RPP component servers.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=3)


def await_phase(path, processes, deadline):
    while not path.exists():
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError(f"Endpoint {process.pid} exited ({process.returncode}); inspect worker.log/echo.log")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Benchmark watchdog waiting for {path.name}")
        time.sleep(0.005)


def environment():
    packages = {}
    for package in ("rpp-common", "rpp-py", "rpp-plugin-registrator", "rpp-orchestrator", "pycapnp", "rclpy"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    result = {"platform": platform.platform(), "machine": platform.machine(),
              "python": sys.version, "python_executable": sys.executable,
              "logical_cpus": os.cpu_count(), "affinity": sorted(os.sched_getaffinity(0)),
              "packages": packages,
              "environment": {name: os.environ.get(name) for name in (
                  "ROS_DISTRO", "RMW_IMPLEMENTATION", "ROS_DOMAIN_ID", "ROS_LOCALHOST_ONLY",
                  "CYCLONEDDS_URI", "FASTRTPS_DEFAULT_PROFILES_FILE", "FASTDDS_DEFAULT_PROFILES_FILE")}}
    cpuinfo = Path("/proc/cpuinfo").read_text()
    result["cpu_model"] = next((line.split(":", 1)[1].strip() for line in cpuinfo.splitlines()
                                if line.startswith("model name")), None)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=False)
    result["demos_revision"] = revision.stdout.strip() if revision.returncode == 0 else None
    return result


def command(config, config_path, args, *, echo=False):
    language = config["receiver"] if echo else config["sender"]
    if language == "python":
        result = [sys.executable, str(ROOT / "python_worker.py")]
    else:
        executable = args.cpp_rpp if config["backend"] == "rpp" else args.cpp_ros
        resolved = shutil.which(executable)
        if resolved is None:
            raise FileNotFoundError(f"Cannot find {executable}; build/source the benchmark package first")
        result = [resolved]
    result.extend(["--config", str(config_path)])
    if echo:
        result.append("--echo")
    return result


def run_case(config, args):
    directory = Path(config["directory"])
    directory.mkdir()
    config_path = directory / "config.json"
    write_json(config_path, config)
    with ExitStack() as stack:
        processes = []
        child_env = os.environ.copy()
        if config["backend"] == "rpp":
            state = json.loads(Path(config["state"]).read_text(encoding="utf-8"))
            child_env["RPP_HOME"] = state["home"]
        commands = []
        roles = [True, False] if config["backend"] == "ros2" and config["placement"] == "subprocess" else [False]
        for echo in roles:
            cmd = command(config, config_path, args, echo=echo)
            commands.append(cmd)
            stream = stack.enter_context((directory / ("echo.log" if echo else "worker.log")).open("w"))
            process = subprocess.Popen(cmd, stdout=stream, stderr=subprocess.STDOUT,
                                       env=child_env, start_new_session=True)
            stack.callback(stop, process)
            processes.append(process)
        write_json(directory / "commands.json", commands)
        await_phase(
            directory / "ready.json", processes,
            time.monotonic() + args.startup_timeout + args.warmup +
            args.reply_timeout * PREFLIGHT_ATTEMPTS)
        roots = [process.pid for process in processes]
        before = cpu_snapshot(roots)
        cpu_begin = time.monotonic()
        (directory / "go").touch()
        await_phase(directory / "done.json", processes, time.monotonic() + args.duration + args.watchdog_slack)
        after = cpu_snapshot(roots)
        cpu_elapsed = time.monotonic() - cpu_begin
        write_json(directory / "cpu.json", cpu_delta(before, after, cpu_elapsed))
        (directory / "release").touch()
        worker = processes[-1]
        worker.wait(timeout=args.startup_timeout)
        if worker.returncode != 0:
            raise RuntimeError(f"Worker exited {worker.returncode}; inspect worker.log")
    return summarize(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, help="Directory created by prepare.py; needed for RPP")
    parser.add_argument("--output", type=Path, required=True, help="New results directory")
    parser.add_argument("--backend", nargs="+", choices=("rpp", "ros2"), default=["rpp", "ros2"])
    parser.add_argument("--case", nargs="+", choices=tuple(CASES), default=list(CASES))
    parser.add_argument("--profiles", type=Path, default=ROOT / "profiles.json")
    parser.add_argument("--profile", nargs="+", help="Profile names; default: every profile")
    parser.add_argument("--rate-hz", type=float, help="Override the requested exchange rate for selected profiles")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument("--warmup", type=float, default=2)
    parser.add_argument("--reply-timeout", type=float, default=2)
    parser.add_argument("--startup-timeout", type=float, default=30)
    parser.add_argument("--watchdog-slack", type=float, default=15)
    parser.add_argument("--ros-qos", nargs="+", choices=tuple(ROS_QOS_MODES),
                        default=tuple(ROS_QOS_MODES),
                        help="ROS QoS modes to measure; defaults to reliable and sensor")
    parser.add_argument("--cpp-rpp", default="rpp_bench_rpp_cpp")
    parser.add_argument("--cpp-ros", default="rpp_bench_ros_cpp")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--plan", action="store_true", help="Print cases without launching endpoints")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("CPU accounting currently requires Linux /proc")
    for name in ("duration", "reply_timeout", "startup_timeout", "watchdog_slack"):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            parser.error(f"{name} must be positive and finite")
    if not math.isfinite(args.warmup) or args.warmup < 0 or args.repeats < 1:
        parser.error("warmup must be nonnegative and repeats must be positive")
    if len(args.ros_qos) != len(set(args.ros_qos)):
        parser.error("Each --ros-qos mode may be selected only once")
    if "rpp" in args.backend and args.state is None:
        parser.error("--state is required for RPP cases")
    profiles = json.loads(args.profiles.read_text(encoding="utf-8"))
    selected = args.profile or list(profiles)
    for name in selected:
        if name not in profiles:
            parser.error(f"Unknown profile: {name}")
        profile = profiles[name]
        if args.rate_hz is not None:
            profile["rate_hz"] = args.rate_hz
        if not isinstance(profile.get("payload_bytes"), int) or not 0 <= profile["payload_bytes"] <= 64 * 1024 * 1024:
            parser.error(f"{name}: payload_bytes must be an integer between 0 and 64 MiB")
        if not isinstance(profile.get("rate_hz"), (int, float)) or not math.isfinite(profile["rate_hz"]) or not 0 < profile["rate_hz"] <= 1e6:
            parser.error(f"{name}: rate_hz must be positive and at most 1 MHz")
        if profile["rate_hz"] * args.duration > 10_000_000:
            parser.error(f"{name}: more than ten million raw samples per case; reduce duration or rate")
    output = args.output.expanduser().resolve()
    plan = []
    for backend in args.backend:
        for case in args.case:
            sender, receiver, placement = CASES[case]
            for name in selected:
                # RPP has one reliable transport, so it is measured once. Each
                # ROS QoS mode is then compared with that same RPP baseline.
                qos_modes = args.ros_qos if backend == "ros2" else (None,)
                for ros_qos in qos_modes:
                    for repeat in range(1, args.repeats + 1):
                        config = dict(
                            profiles[name], backend=backend, case=case, profile=name, repeat=repeat,
                            sender=sender, receiver=receiver, placement=placement,
                            duration_s=args.duration, warmup_s=args.warmup,
                            startup_timeout_s=args.startup_timeout, reply_timeout_s=args.reply_timeout,
                            cpp_server=shutil.which(args.cpp_rpp) or args.cpp_rpp,
                            python_server=str(ROOT / "python_server.py"),
                            topic="/rpp_benchmark_" + uuid.uuid4().hex,
                            state=str(args.state.expanduser().resolve() / "state.json") if args.state else None,
                            directory=str(output / (
                                f"{backend}-{case}-{name}-{ros_qos + '-' if ros_qos else ''}{repeat}")))
                        if ros_qos:
                            config.update(ros_qos=ros_qos, **ROS_QOS_MODES[ros_qos])
                        plan.append(config)
    random.Random(args.seed).shuffle(plan)
    if args.plan:
        print(json.dumps(plan, indent=2))
        return
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "environment.json", environment())
    write_json(output / "plan.json", plan)
    results, failures = [], []
    for index, config in enumerate(plan, 1):
        qos_label = f" {config['ros_qos']}" if config.get("ros_qos") else ""
        label = f"{config['backend']} {config['case']} {config['profile']}{qos_label} #{config['repeat']}"
        print(f"[{index}/{len(plan)}] {label}", flush=True)
        try:
            result = run_case(config, args)
            results.append(result)
            if result["successful"] == 0:
                failures.append({"config": config, "error": "No successful measured replies"})
        except Exception as error:
            failures.append({"config": config, "error": str(error)})
            print(f"  FAILED: {error}", file=sys.stderr, flush=True)
        write_json(output / "failures.json", failures)
        write_report(output, results)
    print(f"Results: {output / 'report.html'} (Markdown: {output / 'report.md'})")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

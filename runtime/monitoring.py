#!/usr/bin/env python3

"""Monitor various cgroup metrics"""

import os
import datetime
import multiprocessing
import subprocess
import time
import argparse
import re
import dataclasses
import typing
import inspect


def now():
    return datetime.datetime.now().strftime("%H-%M-%S-%f")


def log(msg):
    print(f"{now()} -- INFO: [{__name__}] {msg}")


def read(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception as e:
        log(f"Failed to read from path '{path}': {e}")


def write(path, value, append=False):
    try:
        with open(path, "a" if append else "w") as f:
            return f.write(value)
    except Exception as e:
        log(f"Failed to write to path: '{path}': {e}")
        return 0


def cg_read(path):
    return read(os.path.join(_FLAGS.cgroup, path))


def cg_write(path, value, append=False):
    return write(os.path.join(_FLAGS.cgroup, path), value, append=append)


def cg_procs():
    procs = cg_read("cgroup.procs")
    if procs is None:
        return []
    return list(map(int, list(filter(None, procs.split("\n")))))


def parse_cmdline_flags():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", type=str, help="Command to start the workload")
    parser.add_argument("--output", type=str, help="Path to the output file")
    parser.add_argument(
        "--probing_freq_seconds",
        type=float,
        help="Frequency of probing cgroup statistics",
    )
    parser.add_argument(
        "--cgroup_refresh_interval",
        type=str,
        help="Cgroup specific list of numa refresh intervals in milliseconds, separated by columns ';'."
        " The first element in each item specified the affected numa node. "
        "e.g. 0,1000;1,2000",
    )
    parser.add_argument(
        "--node_page_age_intervals",
        type=str,
        help="List of numa page age intervals, separated by columns ';'."
        " The first element in each item specified the affected numa node. "
        "e.g. 0,1000,2000,3000,4000;1,1000,3000,4000",
    )
    parser.add_argument(
        "--node_refresh_intervals",
        type=str,
        help="List of numa refresh intervals in milliseconds, separated by columns ';'."
        " The first element in each item specified the affected numa node. "
        "e.g. 0,1000;1,2000",
    )
    parser.add_argument("--configure_node_workingset_information", action="store_true")

    return parser.parse_args()


class KeyValueStream:
    def __init__(self):
        self.stream = {}

    def push(self, label, value):
        self.stream.setdefault(label, []).append(str(value).strip())

    def to_csv(self):
        header = ",".join(self.stream.keys())
        values = list(zip(*self.stream.values()))
        values = list(map(lambda x: ",".join(x), values))
        return header + "\n" + "\n".join(values)


def configure_node_workingset_information():
    assert _FLAGS.node_page_age_intervals
    assert _FLAGS.node_refresh_intervals

    # Configure the page age intervals
    for page_age_intervals in _FLAGS.node_page_age_intervals.split(";"):
        nid, intervals = page_age_intervals.split(",", 1)
        write(
            f"/sys/devices/system/node/node{nid}/workingset_report/page_age_intervals",
            intervals,
        )

    # Configure the refresh intervals
    for refresh_interval in _FLAGS.node_refresh_intervals.split(";"):
        nid, interval = refresh_interval.split(",", 1)
        write(
            f"/sys/devices/system/node/node{nid}/workingset_report/refresh_interval",
            interval,
        )


def configure_cg_workingset_information():
    for refresh_interval in _FLAGS.cgroup_refresh_interval.split(";"):
        nid, interval = refresh_interval.split(",", 1)
        cg_write(
            "memory.workingset.refresh_interval", f"N{nid}={interval}\n", append=True
        )


def probe_workingset_information():
    ret = {}
    rr = re.compile("(\d+) anon=(\d+) file=(\d+)")
    wss = cg_read("memory.workingset.page_age")
    lines = list(filter(None, re.split("N(\d+)\n", wss)))
    lines.reverse()

    while lines:
        nid = int(lines.pop())
        page_age = lines.pop()
        ret[nid] = []
        for t, anon, file in rr.findall(page_age):
            ret[nid].append((t, anon, file))
    return ret


def probe():
    def push_probed_kv(label, value):
        _KV_STREAM.push(label=label, value=value)

    push_probed_kv(label="timestamp", value=int(time.time() * 1000))

    for m in _METRICS:
        if m == "memory.stat":
            memory_stat_raw = cg_read(m)
            for label, value in re.compile("(\w+) (\d+)").findall(memory_stat_raw):
                push_probed_kv(label=f"memory.stat.{label}", value=value)
        elif m == "memory.workingset.page_age":
            wss = probe_workingset_information()
            for nid, info in wss.items():
                for t, anon, file in info:
                    push_probed_kv(label=f"cold.node.{nid}.{t}ms.anon", value=anon)
                    push_probed_kv(label=f"cold.node.{nid}.{t}ms.file", value=file)
        elif m in ["memory.current", "memory.swap.current"]:
            push_probed_kv(label=m, value=cg_read(m))
        else:
            raise ValueError(f"Unrecognized metric '{m}'")


def configure_swap():
    subprocess.run(["/sbin/swapoff", "-a"], check=True)
    subprocess.run(["/sbin/swapon", "-p", "499", "swapfile"], check=True)
    subprocess.run(["cat", "/proc/swaps"], check=True)


def start_monitoring():
    if _FLAGS.configure_node_workingset_information:
        configure_node_workingset_information()
    configure_cg_workingset_information()
    configure_swap()

    # Drop all cached memory
    log("Flushing all cached memory...")
    subprocess.run("echo 3 > /proc/sys/vm/drop_caches", shell=True, check=True)

    try:
        while _FLAGS.workload_pid in cg_procs():
            probe()
            time.sleep(_FLAGS.probing_freq_seconds)
    except Exception as e:
        log(f"Exception occured while probing cgroup statistics: {e}")

    log(f"Dumping statistics to {_FLAGS.output}.")
    write(_FLAGS.output, _KV_STREAM.to_csv())


def start_workload_process():
    def start_workload_internal():
        subprocess.run(
            f"echo moving pid $$ to '{_FLAGS.cgroup}' && echo $$ > {_FLAGS.cgroup}/cgroup.procs && {_FLAGS.command}",
            shell=True,
        )

    p = multiprocessing.Process(target=start_workload_internal)
    p.start()
    return p.pid


def splash():
    _FLAGS.cgroup = (
        f"/sys/fs/cgroup"
        + read(os.path.join("/proc", str(os.getpid()), "cgroup")).split("::")[1].strip()
    )
    _FLAGS.workload_pid = start_workload_process()

    log(f"Starting to monitor '{_FLAGS.cgroup}'.")
    start_monitoring()


if __name__ == "__main__":
    _FLAGS = parse_cmdline_flags()
    _KV_STREAM = KeyValueStream()
    _METRICS = [
        "memory.stat",
        "memory.swap.current",
        "memory.workingset.page_age",
        "memory.current",
    ]
    splash()

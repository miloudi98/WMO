#!/usr/bin/env python3

"""Proactive reclaim agent"""

import os
import argparse
import time
import re
import datetime


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


def probe_workingset_information():
    ret = {}
    rr = re.compile("(\d+) anon=(\d+) file=(\d+)")
    wss = cg_read("memory.workingset.page_age")
    lines = list(filter(None, re.split("N(\d+)\n", wss)))
    lines.reverse()

    while lines:
        nid = int(lines.pop())
        ret[nid] = []
        page_age = lines.pop()
        for t, anon, file in rr.findall(page_age):
            ret[nid].append((t, anon, file))
    return ret


def start_proactive_reclaim_agent():
    while True:
        time.sleep(_FLAGS.reclaim_freq_seconds)

        wss = probe_workingset_information()[0]
        coldmem = sum(
            int(anon) + int(file)
            for t, anon, file in wss
            if int(t) >= _FLAGS.cold_age_threshold_ms
        )
        memswap_before = int(cg_read("memory.swap.current"))
        log(
            f"Detected {coldmem / (1 << 20)} MiB of cold memory at age {_FLAGS.cold_age_threshold_ms}. memory.swap.current = {memswap_before}."
        )
        cg_write("memory.reclaim", str(coldmem))
        memswap_after = int(cg_read("memory.swap.current"))
        log(
            f"Reclaimed completed. memory.swap.current = {memswap_after}. Delta = {(memswap_after - memswap_before) / (1 << 20)} MiB"
        )


def splash():
    start_proactive_reclaim_agent()


def parse_cmdline_flags():
    parser = argparse.ArgumentParser()
    parser.add_argument("cgroup", type=str, help="Cgroup to attach to")
    parser.add_argument(
        "--reclaim_freq_seconds", type=float, help="Frequency of memory reclaiming"
    )
    parser.add_argument(
        "--cold_age_threshold_ms", type=float, help="Cold age threshold"
    )

    return parser.parse_args()


if __name__ == "__main__":
    _FLAGS = parse_cmdline_flags()
    splash()

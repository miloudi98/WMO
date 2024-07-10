#!/usr/bin/env python3

import datetime
import argparse
import os
import re
import time

argv = None


def now():
    return datetime.datetime.now().strftime("%H-%M-%S-%f")


def log(msg):
    print(f"{now()} -- INFO: [{__name__}] {msg}")


class FS:
    def read(path):
        try:
            with open(path, "r") as f:
                return f.read()
        except Exception as e:
            log(f"Couldn't read {path}. {e}")
            return None

    def write(path, value):
        try:
            with open(path, "w") as f:
                f.write(value)
                return True
        except Exception as e:
            log(f"Couldn't write to {path}. {e}")
            return False

    def cg_read(cgroup_file):
        return FS.read(FS.cg_path(cgroup_file))

    def cg_write(cgroup_file, value):
        return FS.write(FS.cg_path(cgroup_file), value)

    def cg_path(filename):
        return os.path.join(argv.cgroup, filename)


def workingset_page_age():
    ret = {}
    workingset_page_age_raw = FS.cg_read("memory.workingset.page_age")
    nid_pa_intrvls = re.split("N(\d+)\n", workingset_page_age_raw)[1:]
    for nid, pa_intrvl in zip(nid_pa_intrvls[::2], nid_pa_intrvls[1::2]):
        for time, anon, file in re.compile("(\d+) anon=(\d+) file=(\d+)").findall(
            pa_intrvl
        ):
            ret.setdefault(int(nid), []).append((int(time), int(anon), int(file)))
    return ret


def memory_colder_than(age):
    workingset_pa = workingset_page_age()
    ret = 0
    for nid, pa_intrvls in workingset_pa.items():
        for time, anon, file in pa_intrvls:
            ret += anon + file if time >= age else 0
    return ret


def init_zswap_config():
    if argv.disable_zswap:
        FS.write("/sys/module/zswap/parameters/enabled", "0")


class PeriodicPolicy:
    def __init__(self):
        assert argv.policy[0] == "periodic"
        self.cold_age_threshold_milliseconds = int(argv.policy[1])
        self.reclaim_frequency_seconds = int(argv.policy[2])

    def run(self):
        while FS.cg_read("cgroup.procs") not in [None, ""]:
            cold_mem = memory_colder_than(self.cold_age_threshold_milliseconds)
            log(
                f"Reclaiming {cold_mem} ({cold_mem / (1 << 20)} MiB) from {argv.cgroup}."
            )

            FS.cg_write("memory.reclaim", str(cold_mem))
            time.sleep(self.reclaim_frequency_seconds)


def splash():
    init_zswap_config()

    if argv.policy[0] == "periodic":
        PeriodicPolicy().run()
    else:
        raise ValueError(f"Unrecognized policy {argv.policy[0]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("cgroup", type=str, help="Cgroup being managed by the agent.")
    parser.add_argument("--disable_zswap", action="store_true")
    parser.add_argument(
        "--policy",
        nargs="+",
        type=str,
        help="""The reclaim policy of the agent regarding the specified cgroup. 
        Usage: --policy <policy_name> [<policy_args>].
        Policies currently supported are:
        * 'periodic'
          -- $1: cold_age_threshold_milliseconds
          -- $2: reclaim_frequency_seconds
        """,
    )

    argv = parser.parse_args()
    splash()

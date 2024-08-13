#!/usr/bin/env python3

import argparse
import datetime
import time
import multiprocessing
import subprocess
import os
import re

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


class CgroupMonitor:
    def __init__(self):
        self.statistics = {}

    def monitor(self, process):
        metrics = [
            "memory.stat",
            "memory.current",
            "memory.swap.current",
            "memory.zswap.current",
            "memory.workingset.page_age",
            "timestamp",
        ]
        while process.is_alive():
            for m in metrics:
                self._process_metric(m)
            time.sleep(argv.monitoring_frequency)

    def dump(self, out):
        # TODO: Manually dump this as a csv file instead of relying on pandas....
        import pandas

        rows = zip(*self.statistics.values())
        cols = list(self.statistics.keys())
        if not os.path.exists(os.path.dirname(os.path.realpath(out))):
            new_path = f"tmp-cgroup-statistics-{now()}"
            log(f"Path {out} doesn't exist! Writing statistics to {new_path} instead!")
            out = new_path

        pandas.DataFrame(rows, columns=cols).to_csv(out, index=False)

    def configure_workingset_reporting():
        for nid, page_age_intervals in map(
            lambda x: x.split(",", 1), argv.numa_page_age_intervals.split(";")
        ):
            FS.write(
                f"/sys/devices/system/node/node{nid}/workingset_report/page_age_intervals",
                page_age_intervals,
            )

        for nid, refresh_interval in map(
            lambda x: x.split(","), argv.numa_refresh_interval.split(";")
        ):
            FS.write(
                f"/sys/devices/system/node/node{nid}/workingset_report/refresh_interval",
                refresh_interval,
            )

        cg_refresh_intervals = []
        for cg_nid, cg_refresh_interval in map(
            lambda x: x.split(","), argv.cgroup_refresh_interval.split(";")
        ):
            cg_refresh_intervals.append(f"N{cg_nid}={cg_refresh_interval}")

        FS.cg_write(
            "memory.workingset.refresh_interval",
            "\n".join(cg_refresh_intervals + [""]),
        )

    def _process_metric(self, metric):
        if metric == "memory.stat":
            kv_list = list(filter(None, FS.cg_read("memory.stat").split("\n")))
            for k, v in map(lambda x: x.split(), kv_list):
                self._add(f"memory.stat.{k}", int(v))
        elif metric in [
            "memory.current",
            "memory.swap.current",
            "memory.zswap.current",
        ]:
            self._add(metric, int(FS.cg_read(metric)))
        elif metric == "timestamp":
            self._add(metric, now())
        elif metric == "memory.workingset.page_age":
            workingset_pa = CgroupMonitor._workingset_page_age()
            for nid, pa_buckets in workingset_pa.items():
                for time, anon, file in pa_buckets:
                    self._add(f"memory.workingset.node.{nid}.{time}ms.anon", anon)
                    self._add(f"memory.workingset.node.{nid}.{time}ms.file", file)
        else:
            raise ValueError(f"Unkown metric: {metric}")

    def _add(self, k, v):
        self.statistics.setdefault(k, []).append(v)

    def _workingset_page_age():
        ret = {}
        workingset_page_age_raw = FS.cg_read("memory.workingset.page_age")
        nid_pa_intrvls = re.split("N(\d+)\n", workingset_page_age_raw)[1:]
        for nid, pa_intrvl in zip(nid_pa_intrvls[::2], nid_pa_intrvls[1::2]):
            for time, anon, file in re.compile("(\d+) anon=(\d+) file=(\d+)").findall(
                pa_intrvl
            ):
                ret.setdefault(int(nid), []).append((int(time), int(anon), int(file)))
        return ret


def workload():
    command = f"echo $$ > {FS.cg_path('cgroup.procs')} && {argv.c}"
    subprocess.run(command, shell=True)


def splash():
    log(argv)

    if os.path.exists(argv.cgroup):
        raise OSError(f"cgroup '{argv.cgroup}' already exists!")
    os.mkdir(argv.cgroup)

    CgroupMonitor.configure_workingset_reporting()

    cgmon = CgroupMonitor()

    workload_process = multiprocessing.Process(target=workload)
    workload_process.start()

    log(f"Starting to Monitor {argv.cgroup}...")
    cgmon.monitor(workload_process)
    cgmon.dump(argv.o)

    log(f"Tearing down container '{argv.cgroup}'.")
    os.rmdir(argv.cgroup)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cgroup", type=str, help="Cgroup in which to run the workload")
    parser.add_argument("--c", type=str, help="Command to start the workload")
    parser.add_argument(
        "--o", type=str, help="Output file containing memory statistics"
    )
    parser.add_argument(
        "--monitoring_frequency",
        type=int,
        help="Frequency of memory statistics collection in seconds",
    )
    parser.add_argument(
        "--numa_page_age_intervals",
        type=str,
        help="List of numa page age intervals, separated by columns ';'."
        " The first element in each item specified the affected numa node. "
        "e.g. 0,1000,2000,3000,4000;1,1000,3000,4000",
    )
    parser.add_argument(
        "--numa_refresh_interval",
        type=str,
        help="List of numa refresh intervals in milliseconds, separated by columns ';'."
        " The first element in each item specified the affected numa node. "
        "e.g. 0,1000;1,2000",
    )
    parser.add_argument(
        "--cgroup_refresh_interval",
        type=str,
        help="Cgroup specific list of numa refresh intervals in milliseconds, separated by columns ';'."
        " The first element in each item specified the affected numa node. "
        "e.g. 0,1000;1,2000",
    )
    argv = parser.parse_args()
    splash()

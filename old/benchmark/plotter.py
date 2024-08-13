#!/usr/bin/env python3

import argparse
import os
import pandas as pd
import matplotlib.pyplot as plt

argv = None


def plot_timeseries(df_list, metric_list):
    for metric in metric_list:
        for name, df in df_list:
            plt.plot(df[metric], label=name)

        plt.xlabel("time (s)")
        plt.ylabel(metric)
        plt.legend()
        plt.title(f"{metric} over time")
        plt.show()


def plot_histograms(df_list, metric_list):
    for metric in metric_list:
        fig, ax = plt.subplots()
        x = list(map(lambda x: x[0], df_list))
        if metric == "runtime":
            p = ax.bar(x, [len(df) for name, df in df_list], label=metric)
        elif metric == "peak_memory_usage":
            p = ax.bar(x, [max(df["memory.current"]) for _, df in df_list], label=metric)

        ax.bar_label(p, label_type="center")
        ax.set_title(f"{metric} histogram")
        plt.xlabel("benchmark")
        plt.ylabel(metric)
        ax.legend()
        plt.show()


def splash():
    assert len(argv.benchmarks) > 0

    df_list = list(map(lambda x: (x, pd.read_csv(x)), argv.benchmarks))

    time_series_metrics = [
        metric
        for (metric, plot_type) in map(lambda x: x.split(";"), argv.metrics)
        if plot_type == "timeseries"
    ]
    histogram_metrics = [
        metric
        for (metric, plot_type) in map(lambda x: x.split(";"), argv.metrics)
        if plot_type == "histogram"
    ]

    plot_timeseries(df_list, time_series_metrics)
    plot_histograms(df_list, histogram_metrics)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmarks", nargs="+", help="TODO")
    parser.add_argument("--metrics", nargs="+", help="TODO")

    argv = parser.parse_args()
    splash()

# WMO
Workload Memory Optimization

## Benchmark -- Linux kernel build
   
We are compiling the 6.9.8 kernel release with the [working set extension patch series](https://patchwork.kernel.org/project/linux-mm/list/?series=858486) applied.
The benchmark was executed on a Debian 12.6 (bookworm) machine with 8 hyper-threads and 8GiB of RAM running the aforementioned patched kernel.
```
horayra@debian:~$ cat /boot/config-6.9.8-horayra-final | grep 'WORKINGSET\|ZSWAP\|LRU'
CONFIG_ZSWAP=y
CONFIG_ZSWAP_DEFAULT_ON=y
# CONFIG_ZSWAP_SHRINKER_DEFAULT_ON is not set
# CONFIG_ZSWAP_COMPRESSOR_DEFAULT_DEFLATE is not set
# CONFIG_ZSWAP_COMPRESSOR_DEFAULT_LZO is not set
# CONFIG_ZSWAP_COMPRESSOR_DEFAULT_842 is not set
CONFIG_ZSWAP_COMPRESSOR_DEFAULT_LZ4=y
# CONFIG_ZSWAP_COMPRESSOR_DEFAULT_LZ4HC is not set
# CONFIG_ZSWAP_COMPRESSOR_DEFAULT_ZSTD is not set
CONFIG_ZSWAP_COMPRESSOR_DEFAULT="lz4"
# CONFIG_ZSWAP_ZPOOL_DEFAULT_ZBUD is not set
# CONFIG_ZSWAP_ZPOOL_DEFAULT_Z3FOLD is not set
CONFIG_ZSWAP_ZPOOL_DEFAULT_ZSMALLOC=y
CONFIG_ZSWAP_ZPOOL_DEFAULT="zsmalloc"
CONFIG_LRU_GEN=y
CONFIG_LRU_GEN_ENABLED=y
# CONFIG_LRU_GEN_STATS is not set
CONFIG_LRU_GEN_WALKS_MMU=y
CONFIG_WORKINGSET_REPORT=y
CONFIG_WORKINGSET_REPORT_AGING=y
```

```
$ cat /sys/fs/cgroup/user.slice
cgroup.controllers  cgroup.max.descendants  cgroup.threads  cpu.pressure     io.pressure          memory.low        memory.peak          memory.swap.events          memory.workingset.refresh_interval  pids.current
cgroup.events       cgroup.pressure         cgroup.type     cpu.stat         memory.current       memory.max        memory.pressure      memory.swap.high            memory.workingset.report_threshold  pids.events
cgroup.freeze       cgroup.procs            cpu.idle        cpu.stat.local   memory.events        memory.min        memory.reclaim       memory.swap.max             memory.zswap.current                pids.max
cgroup.kill         cgroup.stat             cpu.max         cpu.weight       memory.events.local  memory.numa_stat  memory.stat          memory.swap.peak            memory.zswap.max                    pids.peak
cgroup.max.depth    cgroup.subtree_control  cpu.max.burst   cpu.weight.nice  memory.high          memory.oom.group  memory.swap.current  memory.workingset.page_age  memory.zswap.writeback              user-1000.slice
```

We use a custom workload runner that takes care of running the workload as well as monitor all the desired cgroup stats. The script is available in ${WMO_ROOT_DIR}/benchmark/runner.py.
We used the following command to start the linux kernel build job as well as the necessary monitoring.

```
cd ${LINUX_6.9.8_DIR}
sudo ./${WMO_ROOT_DIR}/benchmark/runner.py /sys/fs/cgroup/kernel_build_experiment \
     --c 'make mrproper && make localmodconfig && make -j 7'  \
     --o cgroup_statistics_output_file  \
     --monitoring_frequency 1 \
     --numa_page_age_intervals 0,500,1000,1500,2000,2500,3000,3500,4000,4500,5000,5500,6000,6500,7000,7500,8000 \
     --numa_refresh_interval 0,500 \
     --cgroup_refresh_interval 0,500
```

The agent responsible for running the proactive_reclaim_with_workingset_extension policy (more on that down below) is available at ${WMO_ROOT_DIR}/agent.py and is run in a separate shell using the following command.
```
sudo ./${WMO_ROOT_DIR}/agent.py /sys/fs/cgroup/kernel_build_experiment \
     --policy 'periodic' 2000 30
```

We ran three experiments:
1. A "vanilla" kernel build without any agent optimizing its memory usage. That will serve as our baseline.
2. A kernel build + our agent executing the proactive_reclaim_with_workingset_extension policy
3. Kernel build + [Senpai](https://github.com/facebookincubator/senpai/blob/main/senpai.py)

Statistics from the experiments above can be found inside the `${WMO_PROJECT_ROOT}/benchmark/data/linux-kernel` folder.
The results were as follows:

![Figure_5](https://github.com/miloudi98/WMO/assets/141595383/da10fb52-03c6-4a43-9369-c424796167c7)

![Figure_3](https://github.com/miloudi98/WMO/assets/141595383/1821d6f5-041e-4083-b01c-a94d00ad6c3f)

![Figure_4](https://github.com/miloudi98/WMO/assets/141595383/68f2d582-fc64-43fb-83c4-ebdf66a8c0d9)

## Benchmark -- Redis benchmark

"""Sample local computation resources for both comparison systems."""
import subprocess
import threading
import time
import psutil


def run(command, *, timeout, env, cwd=None):
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               stdin=subprocess.DEVNULL, env=env, cwd=cwd)
    stop = threading.Event()
    samples = {'cpu_seconds_sampled': 0.0, 'peak_rss_bytes': None, 'samples': 0}

    def sample():
        target = psutil.Process(process.pid)
        while not stop.is_set():
            try:
                cpu, memory = target.cpu_times(), target.memory_info()
                samples['cpu_seconds_sampled'] = max(samples['cpu_seconds_sampled'], cpu.user+cpu.system)
                samples['peak_rss_bytes'] = max(samples['peak_rss_bytes'] or 0, getattr(memory, 'peak_wset', memory.rss))
                samples['samples'] += 1
            except psutil.Error:
                break
            stop.wait(.02)

    sampler = threading.Thread(target=sample, daemon=True); sampler.start()
    timed_out = False
    try:
        try:
            out, err = process.communicate(timeout=max(1, timeout))
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill(); out, err = process.communicate()
    finally:
        stop.set(); sampler.join()
    return {'退出码': -1 if timed_out else process.returncode,
            'stdout': out.decode('utf-8', errors='replace'),
            'stderr': '计算时间预算耗尽' if timed_out else err.decode('utf-8', errors='replace'),
            '秒': round(time.perf_counter()-started, 3), '计算资源': samples}

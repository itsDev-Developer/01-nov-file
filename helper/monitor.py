"""Resource monitor — real RAM / CPU / etc. numbers from *your* server, minimum to maximum.

Every SAMPLE_EVERY seconds it records the bot process and the server it runs on:
the last 24 h are kept in memory (about 1.5 MB, measured), and a per-day summary (min / avg / max
per metric) is merged into MongoDB every FLUSH_EVERY seconds, so history survives
restarts. Cost: about 0.2 ms of CPU per sample (measured), nothing blocks the loop —
psutil is only ever called with interval=None, and the one network call (a MongoDB
ping) has a timeout.

Read it with /resources.
"""

import asyncio
import glob
import os
import shutil
import time
from collections import deque
from datetime import datetime

import psutil

SAMPLE_EVERY = 30          # seconds between samples
FLUSH_EVERY = 600          # seconds between writes of the daily summary
KEEP = 24 * 3600 // SAMPLE_EVERY
HEARTBEAT = 0.1            # seconds, see Monitor._heartbeat

# key -> (label, unit)
METRICS = {
    "rss_mb": ("Bot RAM", "MB"),
    "cpu_pct": ("Bot CPU", "% core"),
    "sys_ram_pct": ("Server RAM used", "%"),
    "sys_cpu_pct": ("Server CPU", "%"),
    "loop_lag_ms": ("Loop lag", "ms"),
    "tasks": ("asyncio tasks", ""),
    "threads": ("Threads", ""),
    "fds": ("Open files/sockets", ""),
    "net_in_kbps": ("Network in*", "KB/s"),
    "net_out_kbps": ("Network out*", "KB/s"),
    "db_ms": ("MongoDB ping", "ms"),
}


def _round(value):
    return None if value is None else round(float(value), 2)


class Monitor:
    def __init__(self, client, sample_every: float = SAMPLE_EVERY, flush_every: float = FLUSH_EVERY):
        self.client = client
        self.sample_every, self.flush_every = sample_every, flush_every
        self.proc = psutil.Process()
        self.started = time.time()
        self.samples = deque(maxlen=KEEP)          # (timestamp, {metric: value | None})
        self.pending = {}                          # date -> {metric: [min, max, sum, n]} not yet flushed
        self._lag_max = 0.0
        self._net = None                           # (timestamp, bytes_recv, bytes_sent)
        self._tasks = []

    # ---- lifecycle ---------------------------------------------------------
    def start(self):
        self.proc.cpu_percent(interval=None)       # prime: the first call always reports 0.0
        psutil.cpu_percent(interval=None)
        self._tasks = [asyncio.ensure_future(self._heartbeat()), asyncio.ensure_future(self._run())]

    async def stop(self):
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.flush()

    async def _heartbeat(self):
        """Event-loop lag: how much later than asked a short sleep wakes up. Anything that blocks the loop
        (a blocking call, a CPU-heavy handler) shows up here as lag. The sleep is short (0.1 s) on purpose:
        a freeze is only noticed if a timer happens to expire during it, so with a 1 s tick a 450 ms freeze
        was caught less than half the time; at 0.1 s every freeze over 100 ms is caught. Cost: ten
        wake-ups a second, a few microseconds each."""
        while True:
            before = time.monotonic()
            await asyncio.sleep(HEARTBEAT)
            self._lag_max = max(self._lag_max, time.monotonic() - before - HEARTBEAT)

    async def _run(self):
        last_flush = time.monotonic()
        await asyncio.sleep(min(5, self.sample_every))        # first reading soon after start-up
        while True:
            try:
                self.record(await self.take_sample())
                if time.monotonic() - last_flush >= self.flush_every:
                    last_flush = time.monotonic()
                    await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception as e:                            # monitoring must never take the bot down
                print(f"[monitor] {type(e).__name__}: {e}")
            await asyncio.sleep(self.sample_every)

    # ---- sampling -----------------------------------------------------------
    async def take_sample(self) -> dict:
        def safe(fn):
            try:
                return fn()
            except Exception:
                return None

        now = time.time()
        sample = {
            "rss_mb": safe(lambda: self.proc.memory_info().rss / 1024 ** 2),
            "cpu_pct": safe(lambda: self.proc.cpu_percent(interval=None)),
            "sys_ram_pct": safe(lambda: psutil.virtual_memory().percent),
            "sys_cpu_pct": safe(lambda: psutil.cpu_percent(interval=None)),
            "loop_lag_ms": self._lag_max * 1000,
            "tasks": safe(lambda: len(asyncio.all_tasks())),
            "threads": safe(self.proc.num_threads),
            "fds": safe(lambda: self.proc.num_fds() if hasattr(self.proc, "num_fds") else self.proc.num_handles()),
            "net_in_kbps": None, "net_out_kbps": None, "db_ms": None,
        }
        self._lag_max = 0.0

        counters = safe(psutil.net_io_counters)
        if counters:
            if self._net:
                dt = max(now - self._net[0], 1e-6)
                sample["net_in_kbps"] = max(0, counters.bytes_recv - self._net[1]) / 1024 / dt
                sample["net_out_kbps"] = max(0, counters.bytes_sent - self._net[2]) / 1024 / dt
            self._net = (now, counters.bytes_recv, counters.bytes_sent)

        try:
            started = time.perf_counter()
            await asyncio.wait_for(self.client.mongodb.ping(), 5)
            sample["db_ms"] = (time.perf_counter() - started) * 1000
        except Exception:
            pass  # unreachable DB shows up as a gap, not as an error here
        return {k: _round(v) for k, v in sample.items()}

    def record(self, sample: dict, when: float = None):
        when = when or time.time()
        self.samples.append((when, sample))
        day = self.pending.setdefault(datetime.fromtimestamp(when).strftime("%Y-%m-%d"), {})
        for key, value in sample.items():
            if value is None:
                continue
            agg = day.get(key)
            if agg is None:
                day[key] = [value, value, value, 1]
            else:
                agg[0], agg[1], agg[2], agg[3] = min(agg[0], value), max(agg[1], value), agg[2] + value, agg[3] + 1

    # ---- reading ---------------------------------------------------------------
    def window(self, seconds: float, now: float = None) -> dict:
        """{metric: {"now", "min", "avg", "max"}} over the last `seconds` (None where there is no data)."""
        now = now or time.time()
        recent = [s for t, s in self.samples if t >= now - seconds]
        out = {}
        for key in METRICS:
            values = [s[key] for s in recent if s.get(key) is not None]
            out[key] = ({"now": values[-1], "min": min(values), "avg": sum(values) / len(values), "max": max(values)}
                        if values else {"now": None, "min": None, "avg": None, "max": None})
        return out

    def span_seconds(self) -> float:
        return (self.samples[-1][0] - self.samples[0][0]) if len(self.samples) > 1 else 0.0

    # ---- persistence --------------------------------------------------------------
    async def flush(self):
        """Merge the not-yet-saved aggregates into the per-day documents. On failure they are kept
        and merged next time (nothing is lost, nothing counted twice)."""
        for day in list(self.pending):
            try:
                await self.client.mongodb.flush_resource_stats(day, self.pending[day])
                del self.pending[day]
            except Exception as e:
                print(f"[monitor] could not save {day}: {type(e).__name__}: {e}")
                return


# ---- report -------------------------------------------------------------------------

def _num(value, width=7, whole=False):
    if value is None:
        return "—".rjust(width)
    if whole or abs(value) >= 1000:
        return f"{value:,.0f}".rjust(width)
    return f"{value:.1f}".rjust(width)


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d}d {h}h" if d else (f"{h}h {m}m" if h else f"{m}m")


def render_report(monitor: Monitor, days: list, hours: int, extras: dict) -> str:
    """HTML for /resources. `days` = per-day documents from MongoDB, newest first."""
    window = monitor.window(hours * 3600)
    covered = min(monitor.span_seconds(), hours * 3600)
    rows = [f"{'Metric':<22}{'now':>7}{'min':>7}{'avg':>7}{'max':>7}"]
    for key, (label, unit) in METRICS.items():
        w = window[key]
        name = f"{label} ({unit})" if unit else label
        whole = key in ("tasks", "threads", "fds")
        rows.append(f"{name[:22]:<22}" + "".join(_num(w[c], whole=whole) for c in ("now", "min", "avg", "max")))

    day_rows = ["Day    RAM MB min/avg/max   CPU avg/max   lag max"]
    for doc in days:
        m = doc.get("m", {})

        def avg(k):
            a = m.get(k)
            return a["sum"] / a["n"] if a and a.get("n") else None

        ram, cpu, lag = m.get("rss_mb"), m.get("cpu_pct"), m.get("loop_lag_ms")
        if not ram:
            continue
        day_rows.append(
            f"{doc['_id'][5:]}  {ram['min']:>5.0f}/{avg('rss_mb'):>5.0f}/{ram['max']:>5.0f}"
            f"   {(avg('cpu_pct') or 0):>4.1f}/{(cpu['max'] if cpu else 0):>5.1f}%"
            f"   {(lag['max'] if lag else 0):>5.0f} ms"
        )

    parts = [
        f"<b>📈 Resource monitor</b>  <i>(up {_duration(time.time() - monitor.started)}, sample every {int(monitor.sample_every)} s)</i>",
        f"<b>Last {_duration(covered) if covered else 'moments'}</b> (window {hours} h)",
        "<pre>" + "\n".join(rows) + "</pre>",
    ]
    if len(day_rows) > 1:
        parts += ["<b>Daily history</b> (kept 60 days)", "<pre>" + "\n".join(day_rows) + "</pre>"]
    parts.append("<b>Now</b>\n" + "\n".join(f"• {k}: <code>{v}</code>" for k, v in extras.items()))
    parts.append("<i>CPU: 100 % = one full core. *Network figures are for the whole server, not just the bot. "
                 "Loop lag = the longest the bot was frozen within each sample; healthy is a few ms.</i>")
    return "\n\n".join(parts)


def gather_extras(client) -> dict:
    """Things that are not time series but explain RAM/disk use."""
    extras = {}
    try:
        usage = shutil.disk_usage(".")
        extras["Disk free"] = f"{usage.free / 1024 ** 3:.1f} GB of {usage.total / 1024 ** 3:.1f} GB"
    except Exception:
        pass
    try:
        from config import LOG_BACKUPS, LOG_FILE_NAME, LOG_MAX_MB
        size = sum(os.path.getsize(f) for f in glob.glob(LOG_FILE_NAME + "*"))
        extras["Log files"] = f"{size / 1024 ** 2:.1f} MB (rotates at {LOG_MAX_MB} MB × {LOG_BACKUPS})"
    except Exception:
        pass
    try:
        from plugins.shortner import shortened_urls_cache
        extras["Short-link cache"] = f"{len(shortened_urls_cache)} entries"
    except Exception:
        pass
    try:
        from helper.geo import _cache
        extras["IP→country cache"] = f"{len(_cache)} entries"
    except Exception:
        pass
    return extras

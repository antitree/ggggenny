#!/usr/bin/env python3
"""
Textual-based live monitor for seccompare runs.

Features:
- Left pane: live tail of instance logs (rotation-friendly)
- Top-right pane: stats with total and per-region counts, last bucket snapshot
- Bottom-right pane: timeline (plotext chart if available, ASCII fallback)
- Header shows PIA region/state/IP, chart mode, bucket size, refresh rate

Controls:
- q: quit
- p: pause/resume updates
- + / -: increase/decrease refresh interval
- t: toggle chart mode (plotext/ascii)
- [ / ]: decrease/increase bucket size (5s step)
- c: clear logs view

CLI:
  python3 textual_monitor.py --logs 'instance_*.log' --metrics 'metrics/*.jsonl' \
      --interval 1.0 --bucket 10 --chart auto
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import io
import json
import os
import subprocess
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import List, Tuple

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Header, Footer, Static, Log
from textual import events


def parse_ts(ts: str) -> float:
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        return dt.timestamp()
    except Exception:
        return time.time()


class FileTail:
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.positions: dict[str, int] = {}

    def read_new_lines(self) -> List[Tuple[str, str]]:
        lines: List[Tuple[str, str]] = []
        files = sorted(glob.glob(self.pattern))
        for path in files:
            try:
                size = os.path.getsize(path)
                pos = self.positions.get(path, 0)
                if size < pos:
                    pos = 0  # rotated/truncated
                if size > pos:
                    with open(path, "rb") as f:
                        f.seek(pos)
                        chunk = f.read()
                    self.positions[path] = pos + len(chunk)
                    text = chunk.decode("utf-8", errors="replace")
                    for ln in text.splitlines():
                        lines.append((path, ln))
                else:
                    self.positions[path] = size
            except FileNotFoundError:
                self.positions.pop(path, None)
            except Exception:
                pass
        return lines


class MetricsAgg:
    def __init__(self, metrics_glob: str, bucket_seconds: int = 10, max_buckets: int = 72):
        self.tail = FileTail(metrics_glob)
        self.success = 0
        self.fail = 0
        self.per_region = defaultdict(lambda: {"success": 0, "fail": 0})
        self.per_instance = defaultdict(lambda: {"success": 0, "fail": 0})
        self.bucket_seconds = max(1, int(bucket_seconds))
        self.max_buckets = max(1, int(max_buckets))
        self.timeline: deque[Tuple[int, int, int]] = deque()  # (bucket_epoch, succ, fail)
        self.bucket_map: dict[int, List[int]] = {}

    def _bucket_start(self, ts: float) -> int:
        return int(ts - (ts % self.bucket_seconds))

    def _ensure_bucket(self, b: int):
        if b not in self.bucket_map:
            self.bucket_map[b] = [0, 0]
            self.timeline.append((b, 0, 0))
            while len(self.timeline) > self.max_buckets:
                old_b, _, _ = self.timeline.popleft()
                self.bucket_map.pop(old_b, None)

    def ensure_buckets_to(self, now_ts: float):
        if not self.timeline:
            self._ensure_bucket(self._bucket_start(now_ts))
            return
        last_b = self.timeline[-1][0]
        target_b = self._bucket_start(now_ts)
        b = last_b
        while b < target_b:
            b += self.bucket_seconds
            self._ensure_bucket(b)

    def update(self):
        for _path, line in self.tail.read_new_lines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            ok = bool(obj.get("success"))
            self.success += 1 if ok else 0
            self.fail += 0 if ok else 1
            inst = str(obj.get("instance_id") or "unknown")
            reg = str(obj.get("batch_region") or "unknown")
            if ok:
                self.per_instance[inst]["success"] += 1
                self.per_region[reg]["success"] += 1
            else:
                self.per_instance[inst]["fail"] += 1
                self.per_region[reg]["fail"] += 1
            ts = parse_ts(obj.get("ts") or "")
            b = self._bucket_start(ts)
            self._ensure_bucket(b)
            self.bucket_map[b][0 if ok else 1] += 1
            # sync deque tuple
            for i, (be, _, _) in enumerate(self.timeline):
                if be == b:
                    s, f = self.bucket_map[b]
                    self.timeline[i] = (b, s, f)
                    break

    def set_bucket_seconds(self, sec: int):
        self.bucket_seconds = max(1, int(sec))
        self.timeline.clear()
        self.bucket_map.clear()


class StatsPane(Static):
    def update_stats(self, metrics: MetricsAgg, bucket_seconds: int):
        total = metrics.success + metrics.fail
        lines = [
            f"Total: {total}  Success: {metrics.success}  Fail: {metrics.fail}",
        ]
        if metrics.timeline:
            _, s, f = metrics.timeline[-1]
            lines.append(f"Last {bucket_seconds}s  S:{s} F:{f}")
        # Top 6 regions
        regs = sorted(metrics.per_region.items(), key=lambda kv: -(kv[1]['success']+kv[1]['fail']))[:6]
        lines.append("Regions:")
        for reg, c in regs:
            lines.append(f"  {reg:18s} S:{c['success']:4d} F:{c['fail']:4d}")
        self.update("\n".join(lines))


def render_timeline_ascii(metrics: "MetricsAgg", width: int, height: int) -> str:
    chars = " .:-=+*#%@"
    data = list(metrics.timeline)
    if not data:
        return "(no data)"
    # Fit to width
    data = data[-max(1, width - 2):]
    maxv = max(1, max(s + f for _, s, f in data))
    s_line = []
    f_line = []
    for _, s, f in data:
        v = s + f
        idx = int((len(chars) - 1) * (v / maxv)) if maxv else 0
        s_line.append('S' if s and not f else chars[idx])
        f_line.append('F' if f and not s else ' ')
    out = ["".join(s_line).ljust(width - 1)]
    if height >= 2:
        out.append("".join(f_line).ljust(width - 1))
    return "\n".join(out)


def render_timeline_plotext(metrics: "MetricsAgg", width: int, height: int, bucket_seconds: int):
    try:
        import plotext as plt  # type: ignore
    except Exception:
        return render_timeline_ascii(metrics, width, height)
    data = list(metrics.timeline)
    if not data:
        return "(no data)"
    succ = [s for _, s, _ in data]
    fail = [f for _, _, f in data]
    max_points = max(1, width - 6)
    if len(succ) > max_points:
        succ = succ[-max_points:]
        fail = fail[-max_points:]
    x = list(range(1, len(succ) + 1))
    try:
        plt.clear_figure()
    except Exception:
        try:
            plt.clf()
        except Exception:
            pass
    try:
        plt.plotsize(max(10, width - 2), max(3, height - 1))
    except Exception:
        try:
            plt.subplotsize(max(3, height - 1), max(10, width - 2))
        except Exception:
            pass
    try:
        plt.title("Success / Failure")
        plt.plot(x, succ, label='success', color='green')
        plt.plot(x, fail, label='failure', color='red')
        plt.ylim(0, max(1, max(succ + fail)))
        plt.xlim(1, len(x))
        plt.xlabel(f"last {len(x)} buckets ({bucket_seconds}s each)")
        plt.ylabel("events")
        plt.legend(True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            plt.show()
        return buf.getvalue()
    except Exception:
        return render_timeline_ascii(metrics, width, height)


class TimelinePane(Static):
    def __init__(self, *a, chart_mode: str = "auto", **kw):
        super().__init__(*a, **kw)
        self.chart_mode = chart_mode  # auto|plotext|ascii
        self._plotext = None
        if chart_mode in ("auto", "plotext"):
            try:
                import plotext as _plt  # type: ignore
                self._plotext = _plt
            except Exception:
                self._plotext = None

    def effective_mode(self) -> str:
        if self.chart_mode == "plotext" and self._plotext is None:
            return "ascii"
        if self.chart_mode == "auto":
            return "plotext" if self._plotext is not None else "ascii"
        return self.chart_mode

    def toggle_mode(self):
        mode = self.effective_mode()
        if self._plotext is None:
            self.chart_mode = "ascii"
        else:
            self.chart_mode = "ascii" if mode == "plotext" else "plotext"

    def render_ascii(self, metrics: MetricsAgg, width: int, height: int) -> str:
        return render_timeline_ascii(metrics, width, height)

    def render_plotext(self, metrics: MetricsAgg, width: int, height: int, bucket_seconds: int) -> str:
        return render_timeline_plotext(metrics, width, height, bucket_seconds)

    def update_timeline(self, metrics: MetricsAgg, bucket_seconds: int):
        # Determine current size from the widget's content region
        cw = max(30, self.size.width or 80)
        ch = max(4, self.size.height or 10)
        mode = self.effective_mode()
        if mode == "plotext":
            s = self.render_plotext(metrics, cw, ch, bucket_seconds)
        else:
            s = self.render_ascii(metrics, cw, ch)
        self.update(s)


class MonitorApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    # Header/Footer are built-ins; main body uses Horizontal split
    .titlebar {
        background: $accent 20%;
    }
    # Containers
    # Left logs and right vertical split
    # Widgets
    # Give logs more weight
    # Use borders for clarity
    Static, Log {
        border: solid $accent 10%;
    }
    # Layout sizing
    # main row: logs (60%) | right column (40%)
    # right column: stats(top) | timeline(bottom)
    # We'll set sizes programmatically on compose
    """

    # Reactive state
    refresh_interval: float = reactive(1.0)
    paused: bool = reactive(False)
    bucket_seconds: int = reactive(10)
    chart_mode: str = reactive("auto")

    def __init__(self, logs_glob: str, metrics_glob: str, interval: float, bucket: int, chart: str, snapshot_dir: str | None = None, quit_after: float | None = None, debug_log: str | None = None):
        super().__init__()
        self.logs_glob = logs_glob
        self.metrics_glob = metrics_glob
        self.refresh_interval = max(0.2, float(interval))
        self.bucket_seconds = max(1, int(bucket))
        self.chart_mode = chart
        self.snapshot_dir = snapshot_dir
        self.quit_after = quit_after
        self.debug_log = debug_log

        self.logs_tail = FileTail(self.logs_glob)
        self.metrics = MetricsAgg(self.metrics_glob, bucket_seconds=self.bucket_seconds, max_buckets=72)
        self.pia_region = "unknown"
        self.pia_state = "-"
        self.pia_ip = "-"
        self._pia_last = 0.0
        self._log_buffer: deque[str] = deque(maxlen=500)

    def _dbg(self, msg: str):
        if not self.debug_log:
            return
        try:
            with open(self.debug_log, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="row"):
            self.log_view = Log()
            self.log_view.border_title = "Logs"
            # Configure if supported by this Textual version
            if hasattr(self.log_view, "highlight"):
                self.log_view.highlight = False
            if hasattr(self.log_view, "markup"):
                self.log_view.markup = False
            yield self.log_view
            with Vertical():
                self.stats_view = StatsPane()
                self.stats_view.border_title = "Stats"
                yield self.stats_view
                self.timeline_view = TimelinePane(chart_mode=self.chart_mode)
                self.timeline_view.border_title = "Timeline"
                yield self.timeline_view
        yield Footer()

    def on_mount(self):
        # Sizing: logs 60% width, right column split 40%
        row = self.query_one("#row", Horizontal)
        row.styles.height = "1fr"
        # Set relative widths
        self.log_view.styles.width = "60%"
        self.stats_view.styles.height = "1fr"
        self.timeline_view.styles.height = "1fr"
        # Timers
        # Keep a handle to the tick timer so we can adjust interval
        self._tick_timer = self.set_interval(self.refresh_interval, self._tick, name="tick")
        self.set_interval(3.0, self._poll_pia, name="pia")
        # Seed initial content so panes aren't empty
        self.log_view.write("[tui] monitor started")
        try:
            self._poll_pia()
            self.metrics.ensure_buckets_to(time.time())
            self.stats_view.update_stats(self.metrics, self.bucket_seconds)
            self.timeline_view.update_timeline(self.metrics, self.bucket_seconds)
        except Exception as e:
            self.log_view.write(f"[tui:init-error] {e}")
        self.bell()
        if self.quit_after and self.quit_after > 0:
            self.set_timer(self.quit_after, lambda: self.exit())

    def _tick(self):
        if self.paused:
            return
        # Logs
        for path, ln in self.logs_tail.read_new_lines():
            name = os.path.basename(path)
            line = f"[{name}] {ln}"
            self._log_buffer.append(line)
            self.log_view.write(line)
        # Metrics
        self.metrics.update()
        self.metrics.ensure_buckets_to(time.time())
        # Update panes
        self.stats_view.update_stats(self.metrics, self.bucket_seconds)
        self.timeline_view.update_timeline(self.metrics, self.bucket_seconds)
        # Update header subtitle with PIA info
        mode = self.timeline_view.effective_mode()
        self.sub_title = f"pia={self.pia_region}:{self.pia_state}:{self.pia_ip} | chart={mode} | bucket={self.bucket_seconds}s | r={self.refresh_interval:.1f}s"
        # Write snapshot files for offline validation
        if self.snapshot_dir:
            try:
                os.makedirs(self.snapshot_dir, exist_ok=True)
                with open(os.path.join(self.snapshot_dir, "header.txt"), "w", encoding="utf-8") as f:
                    f.write(self.sub_title + "\n")
                # stats
                stats_text = []
                total = self.metrics.success + self.metrics.fail
                stats_text.append(f"Total: {total}  Success: {self.metrics.success}  Fail: {self.metrics.fail}")
                if self.metrics.timeline:
                    _, s, ff = self.metrics.timeline[-1]
                    stats_text.append(f"Last {self.bucket_seconds}s  S:{s} F:{ff}")
                regs = sorted(self.metrics.per_region.items(), key=lambda kv: -(kv[1]['success']+kv[1]['fail']))[:6]
                stats_text.append("Regions:")
                for reg, c in regs:
                    stats_text.append(f"  {reg:18s} S:{c['success']:4d} F:{c['fail']:4d}")
                with open(os.path.join(self.snapshot_dir, "stats.txt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(stats_text))
                # timeline
                width = 80
                height = 10
                tl = render_timeline_plotext(self.metrics, width, height, self.bucket_seconds)
                if not tl:
                    tl = render_timeline_ascii(self.metrics, width, height)
                with open(os.path.join(self.snapshot_dir, "timeline.txt"), "w", encoding="utf-8") as f:
                    f.write(tl)
                # logs
                with open(os.path.join(self.snapshot_dir, "logs.txt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(list(self._log_buffer)[-200:]))
            except Exception as e:
                self._dbg(f"snapshot error: {e}")

    def _poll_pia(self):
        try:
            out = subprocess.run(["piactl", "get", "region"], capture_output=True, text=True, timeout=1.5)
            self.pia_region = (out.stdout or "").strip() or "unknown"
        except Exception:
            self.pia_region = "na"
        try:
            out = subprocess.run(["piactl", "get", "connectionstate"], capture_output=True, text=True, timeout=1.5)
            self.pia_state = (out.stdout or "").strip() or "-"
        except Exception:
            self.pia_state = "na"
        try:
            out = subprocess.run(["piactl", "get", "vpnip"], capture_output=True, text=True, timeout=1.5)
            self.pia_ip = (out.stdout or "").strip() or "-"
        except Exception:
            self.pia_ip = "na"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("p", "toggle_pause", "Pause"),
        ("+", "faster", "Faster"),
        ("-", "slower", "Slower"),
        ("t", "toggle_chart", "Chart"),
        ("[", "bucket_down", "Bucket-"),
        ("]", "bucket_up", "Bucket+"),
        ("c", "clear_logs", "Clear Logs"),
    ]

    def action_toggle_pause(self):
        self.paused = not self.paused
        self.log_view.write(f"[tui] paused={self.paused}")

    def action_quit(self):
        # Ensure exit works even if default binding varies by version
        self.exit()

    def _reset_tick_timer(self):
        # Reset the tick timer with new interval
        try:
            if hasattr(self, "_tick_timer") and self._tick_timer is not None:
                self._tick_timer.stop()
        except Exception:
            pass
        self._tick_timer = self.set_interval(self.refresh_interval, self._tick, name="tick")

    def action_faster(self):
        self.refresh_interval = max(0.1, self.refresh_interval - 0.1)
        self._reset_tick_timer()
        self.log_view.write(f"[tui] refresh={self.refresh_interval:.1f}s")

    def action_slower(self):
        self.refresh_interval = min(5.0, self.refresh_interval + 0.1)
        self._reset_tick_timer()
        self.log_view.write(f"[tui] refresh={self.refresh_interval:.1f}s")

    def action_toggle_chart(self):
        self.timeline_view.toggle_mode()
        self.log_view.write(f"[tui] chart={self.timeline_view.effective_mode()}")

    def action_bucket_down(self):
        self.bucket_seconds = max(1, self.bucket_seconds - 5)
        self.metrics.set_bucket_seconds(self.bucket_seconds)
        self.log_view.write(f"[tui] bucket={self.bucket_seconds}s")

    def action_bucket_up(self):
        self.bucket_seconds = min(120, self.bucket_seconds + 5)
        self.metrics.set_bucket_seconds(self.bucket_seconds)
        self.log_view.write(f"[tui] bucket={self.bucket_seconds}s")

    def action_clear_logs(self):
        self.log_view.clear()

    # Extra-wide key handling for older/newer Textual versions
    async def on_key(self, event: events.Key) -> None:  # type: ignore
        key = (event.key or "").lower()
        if key == "q":
            self.exit()
        elif key == "p":
            self.action_toggle_pause()
        elif key == "+":
            self.action_faster()
        elif key == "-":
            self.action_slower()
        elif key == "t":
            self.action_toggle_chart()
        elif key == "[":
            self.action_bucket_down()
        elif key == "]":
            self.action_bucket_up()
        elif key == "c":
            self.action_clear_logs()


def main():
    ap = argparse.ArgumentParser(description="Textual monitor for seccompare runs")
    ap.add_argument("--logs", default="instance_*.log", help="Glob for instance logs (default: instance_*.log)")
    ap.add_argument("--metrics", default="metrics/*.jsonl", help="Glob for metrics files (default: metrics/*.jsonl)")
    ap.add_argument("--interval", type=float, default=1.0, help="Refresh interval seconds (default: 1.0)")
    ap.add_argument("--bucket", type=int, default=10, help="Timeline bucket size in seconds (default: 10)")
    ap.add_argument("--chart", choices=["auto", "plotext", "ascii"], default="auto", help="Timeline chart renderer (default: auto)")
    ap.add_argument("--snapshot-dir", default=None, help="Directory to write periodic snapshots (header/stats/timeline/logs)")
    ap.add_argument("--quit-after", type=float, default=None, help="Exit after N seconds (for testing)")
    ap.add_argument("--debug-log", default=None, help="Write debug logs to this file")
    ap.add_argument("--headless", action="store_true", help="Run in headless snapshot mode without Textual UI")
    args = ap.parse_args()

    if args.headless:
        # Minimal headless loop: poll and write snapshots (header/stats/timeline), then exit after quit-after
        logs_tail = FileTail(args.logs)
        metrics = MetricsAgg(args.metrics, bucket_seconds=args.bucket, max_buckets=72)
        start = time.time()
        snap_dir = args.snapshot_dir or "snapshots"
        os.makedirs(snap_dir, exist_ok=True)
        while True:
            # Logs
            for path, ln in logs_tail.read_new_lines():
                pass  # headless: we only snapshot aggregated logs via Textual app; skip
            # Metrics
            metrics.update()
            metrics.ensure_buckets_to(time.time())
            # Write header and stats snapshots
            try:
                # header (no PIA in headless)
                header = f"chart=auto | bucket={args.bucket}s | r={args.interval:.1f}s"
                with open(os.path.join(snap_dir, "header.txt"), "w", encoding="utf-8") as f:
                    f.write(header + "\n")
                # stats
                total = metrics.success + metrics.fail
                lines = [
                    f"Total: {total}  Success: {metrics.success}  Fail: {metrics.fail}",
                ]
                if metrics.timeline:
                    _, s, ff = metrics.timeline[-1]
                    lines.append(f"Last {args.bucket}s  S:{s} F:{ff}")
                regs = sorted(metrics.per_region.items(), key=lambda kv: -(kv[1]['success']+kv[1]['fail']))[:6]
                lines.append("Regions:")
                for reg, c in regs:
                    lines.append(f"  {reg:18s} S:{c['success']:4d} F:{c['fail']:4d}")
                with open(os.path.join(snap_dir, "stats.txt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            except Exception:
                pass
            # Write timeline snapshot
            tl = render_timeline_plotext(metrics, 80, 10, args.bucket)
            if not tl:
                tl = render_timeline_ascii(metrics, 80, 10)
            with open(os.path.join(snap_dir, "timeline.txt"), "w", encoding="utf-8") as f:
                f.write(tl)
            # Time control
            if args.quit_after and (time.time() - start) >= args.quit_after:
                break
            time.sleep(max(0.2, float(args.interval)))
        return
    app = MonitorApp(args.logs, args.metrics, args.interval, args.bucket, args.chart, snapshot_dir=args.snapshot_dir, quit_after=args.quit_after, debug_log=args.debug_log)
    app.run()


if __name__ == "__main__":
    main()

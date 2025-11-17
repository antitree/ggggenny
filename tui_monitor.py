#!/usr/bin/env python3
import argparse
import curses
import glob
import io
import json
import os
import signal
import subprocess
import time
import contextlib
from collections import defaultdict, deque
from datetime import datetime


def parse_ts(ts: str) -> float:
    # Expecting ISO-like without timezone: YYYY-MM-DDTHH:MM:SS
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        return dt.timestamp()
    except Exception:
        return time.time()


class FileTail:
    def __init__(self, pattern):
        self.pattern = pattern
        self.positions = {}
        self.buffers = defaultdict(list)

    def read_new_lines(self):
        lines = []
        files = sorted(glob.glob(self.pattern))
        for path in files:
            try:
                size = os.path.getsize(path)
                pos = self.positions.get(path, 0)
                if size < pos:
                    # File rotated/truncated
                    pos = 0
                if size > pos:
                    with open(path, "rb") as f:
                        f.seek(pos)
                        chunk = f.read()
                        self.positions[path] = pos + len(chunk)
                        try:
                            text = chunk.decode("utf-8", errors="replace")
                        except Exception:
                            text = chunk.decode("latin-1", errors="replace")
                        for ln in text.splitlines():
                            lines.append((path, ln))
                else:
                    self.positions[path] = size
            except FileNotFoundError:
                self.positions.pop(path, None)
            except Exception:
                # Ignore transient read errors
                pass
        return lines


class MetricsAgg:
    def __init__(self, metrics_glob: str, bucket_seconds: int = 10, max_buckets: int = 60):
        self.tail = FileTail(metrics_glob)
        self.success = 0
        self.fail = 0
        self.per_region = defaultdict(lambda: {"success": 0, "fail": 0})
        self.per_instance = defaultdict(lambda: {"success": 0, "fail": 0})
        self.bucket_seconds = max(1, int(bucket_seconds))
        self.max_buckets = max(1, int(max_buckets))
        self.timeline = deque()  # list of (bucket_start_epoch, success_count, fail_count)
        self.bucket_map = {}  # epoch->(succ, fail)

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
        """Ensure buckets exist up to current time, inserting zero buckets if idle."""
        if not self.timeline:
            self._ensure_bucket(self._bucket_start(now_ts))
            return
        last_b = self.timeline[-1][0]
        target_b = self._bucket_start(now_ts)
        b = last_b
        # add empty buckets until we reach target
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
            d_i = self.per_instance[inst]
            d_r = self.per_region[reg]
            if ok:
                d_i["success"] += 1
                d_r["success"] += 1
            else:
                d_i["fail"] += 1
                d_r["fail"] += 1
            ts = parse_ts(obj.get("ts") or "")
            b = self._bucket_start(ts)
            self._ensure_bucket(b)
            self.bucket_map[b][0 if ok else 1] += 1
            # update deque tuple
            # find and replace
            for idx in range(len(self.timeline)):
                if self.timeline[idx][0] == b:
                    s, f = self.bucket_map[b]
                    self.timeline[idx] = (b, s, f)
                    break

    def set_bucket_seconds(self, sec: int):
        # Change the bucket window for future updates; keep cumulative stats
        self.bucket_seconds = max(1, int(sec))
        self.timeline.clear()
        self.bucket_map.clear()


class TUI:
    def __init__(self, stdscr, log_pattern: str, metrics_pattern: str, refresh_interval: float = 1.0, bucket_seconds: int = 10):
        self.stdscr = stdscr
        self.refresh_interval = max(0.2, float(refresh_interval))
        self.logs = FileTail(log_pattern)
        self.bucket_seconds = max(1, int(bucket_seconds))
        self.metrics = MetricsAgg(metrics_pattern, bucket_seconds=self.bucket_seconds, max_buckets=72)  # ~12 minutes by default
        self.log_buffer = deque(maxlen=1000)
        self.paused = False
        self.last_update = 0.0
        self.last_pia_poll = 0.0
        self.pia_region = "unknown"
        self.pia_state = "-"
        self.pia_ip = "-"
        # Try plotext for richer charts
        self._plotext = None
        try:
            import plotext as _plt  # type: ignore
            self._plotext = _plt
        except Exception:
            self._plotext = None
        # chart mode: 'auto' (prefer plotext if available), 'plotext', or 'ascii'
        self.chart_mode = "auto"

    def _put(self, y: int, x: int, text: str, width: int, attr: int = 0):
        try:
            maxlen = max(0, width - 1)
            s = (text or "")[:maxlen]
            self.stdscr.addnstr(y, x, s, maxlen, attr)
        except Exception:
            pass

    def get_effective_chart_mode(self) -> str:
        if self.chart_mode == "plotext" and self._plotext is None:
            return "ascii"
        if self.chart_mode == "auto":
            return "plotext" if self._plotext is not None else "ascii"
        return self.chart_mode

    def draw_header(self, h, w):
        total = self.metrics.success + self.metrics.fail
        regio = sorted(self.metrics.per_region.items(), key=lambda kv: -(kv[1]['success']+kv[1]['fail']))
        top_region = regio[0][0] if regio else "unknown"
        pia = f"pia={self.pia_region}:{self.pia_state}:{self.pia_ip}"
        mode = self.get_effective_chart_mode()
        header = f" SecCompare TUI | total={total} success={self.metrics.success} fail={self.metrics.fail} | top-region={top_region} | {pia} | chart={mode} | bucket={self.bucket_seconds}s | r={self.refresh_interval:.1f}s  (q quit, p pause, +/- speed, t chart, [/] bucket) "
        self._put(0, 0, header.ljust(w), w, curses.A_REVERSE)

    def draw_logs(self, y, x, h, w):
        self._put(y, x, " Logs ", w, curses.A_BOLD)
        start = max(0, len(self.log_buffer) - (h - 1))
        lines = list(self.log_buffer)[start:]
        for i, ln in enumerate(lines[:h-1]):
            self._put(y + 1 + i, x, ln, w)

    def bar(self, count, max_count, width):
        if max_count <= 0:
            return "".ljust(width)
        filled = int(round(width * (count / max_count)))
        return ("#" * filled + " " * (width - filled))

    def draw_stats(self, y, x, h, w):
        self._put(y, x, " Stats ", w, curses.A_BOLD)
        maxw = w - 12
        total = max(1, self.metrics.success + self.metrics.fail)
        self._put(y + 1, x, f" Success: {self.metrics.success:6d} " + self.bar(self.metrics.success, total, maxw), w)
        self._put(y + 2, x, f" Failure: {self.metrics.fail:6d} " + self.bar(self.metrics.fail, total, maxw), w)
        # Last bucket snapshot
        if self.metrics.timeline:
            _, s_last, f_last = self.metrics.timeline[-1]
            self._put(y + 3, x, f" Last {self.bucket_seconds:>3d}s  S:{s_last:4d} F:{f_last:4d}", w)
            row = 4
        else:
            row = 3
        # Top 5 regions
        regs = sorted(self.metrics.per_region.items(), key=lambda kv: -(kv[1]['success']+kv[1]['fail']))[:max(0, min(5, h - (row + 1)))]
        self._put(y + row, x, " Regions:", w)
        for i, (reg, counts) in enumerate(regs):
            line = f"  {reg:18s} S:{counts['success']:4d} F:{counts['fail']:4d}"
            self._put(y + row + 1 + i, x, line, w)

    def draw_timeline(self, y, x, h, w):
        title = " Timeline (10s buckets) "
        self._put(y, x, title, w, curses.A_BOLD)
        if h <= 3 or w <= 20:
            return
        # Prefer plotext if available for nicer chart
        if self.get_effective_chart_mode() == "plotext":
            self._draw_timeline_plotext(y + 1, x, h - 1, w)
        else:
            self._draw_timeline_ascii(y + 1, x, h - 1, w)

    def _draw_timeline_ascii(self, y, x, h, w):
        chars = " .:-=+*#%@"
        maxv = 1
        data = list(self.metrics.timeline)[- (w - 2) :]
        if data:
            maxv = max(maxv, max(s + f for _, s, f in data))
        line_s = []
        line_f = []
        for _, s, f in data:
            v = s + f
            idx = int((len(chars) - 1) * (v / maxv)) if maxv else 0
            line_s.append('S' if s and not f else chars[idx])
            line_f.append('F' if f and not s else ' ')
        self._put(y + 0, x, ''.join(line_s).ljust(w-1), w)
        if h >= 2:
            self._put(y + 1, x, ''.join(line_f).ljust(w-1), w)

    def _draw_timeline_plotext(self, y, x, h, w):
        plt = self._plotext
        if plt is None:
            self._draw_timeline_ascii(y, x, h, w)
            return
        data = list(self.metrics.timeline)
        if not data:
            # nothing yet
            return
        # Use sequential x so labels don’t get cluttered; last N points to fit
        succ = [s for _, s, _ in data]
        fail = [f for _, _, f in data]
        # Fit to pane width
        max_points = max(1, w - 6)
        if len(succ) > max_points:
            succ = succ[-max_points:]
            fail = fail[-max_points:]
        x_vals = list(range(1, len(succ) + 1))
        try:
            plt.clear_figure()
        except Exception:
            try:
                plt.clf()
            except Exception:
                pass
        # Size and style
        try:
            plt.plotsize(w - 2, max(3, h - 1))
        except Exception:
            try:
                plt.subplotsize(max(3, h - 1), w - 2)
            except Exception:
                pass
        try:
            plt.title("Success / Failure")
            plt.plot(x_vals, succ, label='success', color='green')
            plt.plot(x_vals, fail, label='failure', color='red')
            plt.ylim(0, max(1, max(succ + fail)))
            plt.xlim(1, len(x_vals))
            try:
                plt.xlabel(f"last {len(x_vals)} buckets ({self.bucket_seconds}s each)")
                plt.ylabel("events")
            except Exception:
                pass
            plt.legend(True)
            # Capture the chart output to draw inside curses
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                plt.show()
            lines = buf.getvalue().splitlines()
            for i in range(min(h, len(lines))):
                self._put(y + i, x, lines[i], w)
        except Exception:
            # Fallback to ASCII if plotext rendering fails
            self._draw_timeline_ascii(y, x, h, w)

    def update(self):
        # Read new logs
        if not self.paused:
            for path, ln in self.logs.read_new_lines():
                # Prefix with file short name
                name = os.path.basename(path)
                self.log_buffer.append(f"[{name}] {ln}")
            self.metrics.update()
            # Ensure we advance buckets even if idle, for regular 10s snapshots
            self.metrics.ensure_buckets_to(time.time())
        # Poll PIA info every ~3 seconds
        now = time.time()
        if now - self.last_pia_poll >= 3.0:
            self._poll_pia()
            self.last_pia_poll = now

    def _poll_pia(self):
        try:
            reg = subprocess.run(["piactl", "get", "region"], capture_output=True, text=True, timeout=1.5)
            self.pia_region = (reg.stdout or "").strip() or "unknown"
        except Exception:
            self.pia_region = "na"
        try:
            st = subprocess.run(["piactl", "get", "connectionstate"], capture_output=True, text=True, timeout=1.5)
            self.pia_state = (st.stdout or "").strip() or "-"
        except Exception:
            self.pia_state = "na"
        try:
            ip = subprocess.run(["piactl", "get", "vpnip"], capture_output=True, text=True, timeout=1.5)
            self.pia_ip = (ip.stdout or "").strip() or "-"
        except Exception:
            self.pia_ip = "na"

    def loop(self):
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        last_draw = 0
        while True:
            ch = self.stdscr.getch()
            if ch == ord('q'):
                break
            elif ch == ord('p'):
                self.paused = not self.paused
            elif ch == ord('+'):
                self.refresh_interval = max(0.1, self.refresh_interval - 0.1)
            elif ch == ord('-'):
                self.refresh_interval = min(5.0, self.refresh_interval + 0.1)
            elif ch == ord('c'):
                self.log_buffer.clear()
            elif ch == ord('t'):
                # Toggle chart mode between plotext and ascii
                current = self.get_effective_chart_mode()
                # If plotext not available, ensure ascii
                if self._plotext is None:
                    self.chart_mode = "ascii"
                    self.log_buffer.append("[tui] plotext not available; using ascii")
                else:
                    self.chart_mode = "ascii" if current == "plotext" else "plotext"
                    self.log_buffer.append(f"[tui] chart mode: {self.chart_mode}")
            elif ch == ord('['):
                # Decrease bucket window by 5s (min 1s)
                self.bucket_seconds = max(1, self.bucket_seconds - 5)
                self.metrics.set_bucket_seconds(self.bucket_seconds)
                self.log_buffer.append(f"[tui] bucket window: {self.bucket_seconds}s")
            elif ch == ord(']'):
                # Increase bucket window by 5s (max 120s reasonable)
                self.bucket_seconds = min(120, self.bucket_seconds + 5)
                self.metrics.set_bucket_seconds(self.bucket_seconds)
                self.log_buffer.append(f"[tui] bucket window: {self.bucket_seconds}s")

            now = time.time()
            if now - self.last_update >= self.refresh_interval:
                self.update()
                self.last_update = now

            if now - last_draw >= 0.05:
                self.stdscr.erase()
                h, w = self.stdscr.getmaxyx()
                self.draw_header(h, w)
                # Layout: logs left 60%, right column split top/bottom
                left_w = max(10, int(w * 0.6))
                right_w = w - left_w
                # Logs
                self.draw_logs(1, 0, h - 1, left_w)
                # Stats (top-right)
                stats_h = max(5, (h - 1) // 2)
                self.draw_stats(1, left_w, stats_h, right_w)
                # Timeline (bottom-right)
                self.draw_timeline(1 + stats_h, left_w, h - 1 - stats_h, right_w)
                self.stdscr.refresh()
                last_draw = now

            time.sleep(0.05)


def main():
    ap = argparse.ArgumentParser(description="Terminal UI for monitoring seccompare runs.")
    ap.add_argument("--logs", default="instance_*.log", help="Glob for instance logs (default: instance_*.log)")
    ap.add_argument("--metrics", default="metrics/*.jsonl", help="Glob for metrics files (default: metrics/*.jsonl)")
    ap.add_argument("--interval", type=float, default=1.0, help="Refresh interval seconds (default: 1.0)")
    ap.add_argument("--bucket", type=int, default=10, help="Timeline bucket size in seconds (default: 10)")
    ap.add_argument("--chart", choices=["auto", "plotext", "ascii"], default="auto", help="Timeline chart renderer (default: auto)")
    args = ap.parse_args()

    def _run(stdscr):
        app = TUI(stdscr, args.logs, args.metrics, args.interval, bucket_seconds=args.bucket)
        # Set initial chart mode
        app.chart_mode = args.chart
        app.log_buffer.append("[tui] chart mode: {}".format(app.get_effective_chart_mode()))
        app.loop()

    # Ensure Ctrl-C exits cleanly
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    curses.wrapper(_run)


if __name__ == "__main__":
    main()

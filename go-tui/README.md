# SecMon (Go TUI)

K9s-style terminal dashboard built with Go, `tview` and `tcell`.

Features
- Left pane: live tail of logs (`--logs` glob, rotation-friendly)
- Top-right: success/failure totals, last-bucket snapshot, per-region counts
- Bottom-right: timeline chart (ASCII), live-updating in buckets
- Header bar: PIA `region:state:ip`, refresh rate, bucket size

Controls
- q: quit
- p: pause/resume updates
- + / -: increase/decrease refresh interval
- [ / ]: decrease/increase bucket size
- c: clear logs pane

Flags
- `--logs` (default `instance_*.log`)
- `--metrics` (default `metrics/*.jsonl`)
- `--refresh` seconds (default 1.0)
- `--bucket` seconds (default 10)
- `--snapshot-dir` write header/stats/timeline/logs each tick (optional)
- `--quit-after` seconds; exit automatically (optional)
- `--debug` enable extra stderr logging (optional)
- `--headless` run without UI, only snapshots (optional)
- `--simulate` generate synthetic metrics in-process for demo/testing (optional)

Quick start
```
cd go-tui
go mod tidy
go run ./cmd/secmon --simulate --snapshot-dir snapshots --quit-after 10
```

Against real files
```
go run ./cmd/secmon --logs "instance_*.log" --metrics "metrics/*.jsonl" --refresh 1 --bucket 10
```


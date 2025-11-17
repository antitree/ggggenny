# ggggenny

A browser automation and monitoring system for testing automated voting workflows. Features Playwright-based browser automation, real-time TUI dashboards, metrics collection, and VPN region rotation.

## Features

- **Browser Automation**: Playwright-powered Firefox automation for click-through workflows
- **Real-time Monitoring**: Terminal UI dashboards (Go and Python implementations)
- **Metrics Collection**: Structured JSONL format with timing, success rates, and region data
- **VPN Integration**: PIA (Private Internet Access) region rotation for distributed testing
- **Parallel Execution**: Orchestration scripts for running multiple browser instances
- **Log Rotation**: Automatic size-based rotation to prevent disk bloat

## Prerequisites

### Linux

- **Python 3.8+**
- **Go 1.21+** (for TUI dashboard)
- **Firefox** browser
- **PIA VPN client** (optional, for VPN rotation)

### Windows

- **Python 3.8+** (from [python.org](https://www.python.org/downloads/))
- **Go 1.21+** (from [go.dev](https://go.dev/dl/))
- **Firefox** browser
- **Git Bash** or WSL2 (for running bash scripts)
- **PIA VPN client** (optional)

## Installation

### Linux

```bash
# 1. Clone the repository
git clone <repository-url>
cd ggggenny

# 2. Install Python dependencies
pip3 install playwright textual rich matplotlib

# 3. Install Playwright browsers
playwright install firefox

# 4. Build the Go TUI (optional but recommended)
cd go-tui
go mod tidy
go build -o secmon ./cmd/secmon
cd ..

# 5. Make scripts executable
chmod +x run_instances.sh rotating_log.sh test_tui.sh

# 6. Create metrics directory
mkdir -p metrics
```

### Windows

```powershell
# 1. Clone the repository
git clone <repository-url>
cd ggggenny

# 2. Install Python dependencies
pip install playwright textual rich matplotlib

# 3. Install Playwright browsers
playwright install firefox

# 4. Build the Go TUI (optional but recommended)
cd go-tui
go mod tidy
go build -o secmon.exe ./cmd/secmon
cd ..

# 5. Create metrics directory
mkdir metrics
```

**Note**: Bash scripts (`run_instances.sh`, etc.) require Git Bash or WSL2 on Windows.

## Usage

### Quick Start (Demo Mode)

Generate synthetic metrics and view in the dashboard:

```bash
# Generate fake metrics
python3 gen_metrics.py --output metrics/demo.jsonl --duration 60 --rate 2.0

# Run the Go TUI dashboard
cd go-tui
./secmon --metrics "../metrics/demo.jsonl" --refresh 1.0

# Or use Python Textual TUI
python3 textual_monitor.py --metrics "metrics/demo.jsonl"
```

### Single Browser Instance

Run a single automated browser session:

```bash
python3 seccompare_click.py \
  --headless \
  --ephemeral \
  --max-attempts 10 \
  --metrics-file metrics/test.jsonl \
  --instance-id inst1
```

**Key Options:**
- `--headless`: Run browser without visible window
- `--ephemeral`: Use temporary browser profile (fresh state each run)
- `--max-attempts N`: Stop after N attempts
- `--proxy`: Enable HTTP proxy (127.0.0.1:8080)
- `--rotate-ip`: Rotate PIA VPN region on failures
- `--clear-cache`: Clear browser cache between attempts

### Multiple Parallel Instances (Linux/WSL)

Use the orchestration script to run multiple instances with VPN rotation:

```bash
# Syntax: ./run_instances.sh [instances] [attempts_per_batch] [batches]
./run_instances.sh 3 10 2

# This runs:
# - 3 parallel browser instances
# - Each instance makes 10 attempts
# - 2 batches total (VPN region changes between batches)
# - 0 batches = infinite loop
```

### Real-time Monitoring

Monitor running instances with the TUI dashboard:

```bash
# Go TUI (recommended)
cd go-tui
./secmon \
  --logs "../instance_*.log" \
  --metrics "../metrics/*.jsonl" \
  --refresh 1.0 \
  --bucket 10

# Python Textual TUI
python3 textual_monitor.py \
  --logs "instance_*.log" \
  --metrics "metrics/*.jsonl"

# Python Curses TUI
python3 tui_monitor.py \
  --logs "instance_*.log" \
  --metrics "metrics/*.jsonl"
```

**TUI Controls (Go version):**
- `q` - Quit
- `p` - Pause/resume updates
- `+/-` - Adjust refresh interval
- `[/]` - Adjust bucket size
- `c` - Clear logs pane

### Analyze Results

Generate reports from collected metrics:

```bash
# Generate visualization
python3 analyze_metrics.py \
  --input metrics/metrics.jsonl \
  --out results.png

# CSV summary only
python3 analyze_metrics.py --input metrics/metrics.jsonl
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DRY_RUN_PIACTL` | `0` | Set to `1` to simulate PIA commands |
| `PIA_REGION` | random US | Force specific PIA region |
| `PIA_SET_AT_START` | `1` | Reset VPN region at startup |
| `TEST_MODE` | `0` | Enable test mode (skip browser) |
| `LOG_MAX_BYTES` | `5242880` | Max log file size (5MB) |
| `LOG_KEEP` | `5` | Number of rotated logs to keep |
| `METRICS_MAX_BYTES` | `104857600` | Max metrics file size (100MB) |
| `METRICS_KEEP` | `10` | Number of rotated metrics to keep |

### Metrics Format

Each entry in the JSONL metrics file contains:

```json
{
  "ts": "2025-11-15T12:34:56",
  "instance_id": "instance_1",
  "attempt": 1,
  "success": true,
  "reason": "success_text_detected",
  "elapsed_ms": 1500,
  "proxy": false,
  "rotated_on_failure": false,
  "url": "https://example.com/vote",
  "batch_region": "us-california"
}
```

## Project Structure

```
ggggenny/
├── go-tui/                     # Go TUI dashboard
│   ├── cmd/secmon/main.go      # Entry point
│   ├── internal/ui/            # UI components
│   ├── internal/metrics/       # Metrics aggregation
│   ├── internal/tail/          # Log file tailing
│   └── go.mod                  # Go dependencies
├── seccompare_click.py         # Main browser automation script
├── gen_metrics.py              # Synthetic metrics generator
├── textual_monitor.py          # Python Textual TUI
├── tui_monitor.py              # Python curses TUI
├── analyze_metrics.py          # Metrics analyzer
├── run_instances.sh            # Orchestration script
├── rotating_log.sh             # Log rotation helper
└── test_tui.sh                 # Test harness
```

## Troubleshooting

### Common Issues

**Playwright browser not found:**
```bash
playwright install firefox
```

**Permission denied on scripts (Linux):**
```bash
chmod +x *.sh
```

**PIA VPN not responding:**
- Ensure PIA client is installed and running
- Check `piactl` is in PATH
- Set `DRY_RUN_PIACTL=1` to simulate without actual VPN

**Go module errors:**
```bash
cd go-tui
go mod tidy
```

**Windows bash scripts not working:**
- Use Git Bash or WSL2
- Or run Python scripts directly without orchestration

### Logs

- Instance logs: `instance_*.log`
- Metrics files: `metrics/*.jsonl`
- Debug with `--debug` flag in Go TUI

## License

[Add your license here]

## Contributing

[Add contribution guidelines here]

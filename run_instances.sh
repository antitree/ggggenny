#!/usr/bin/env bash
# Run N parallel instances of seccompare_click.py in repeating batches.

# Usage: ./run_instances.sh [INSTANCES] [BATCH_ATTEMPTS] [BATCHES]
# - INSTANCES: number of parallel instances (default 3)
# - BATCH_ATTEMPTS: attempts per instance per batch (default 10)
# - BATCHES: number of batches to run (default 0 = infinite)
# Optional: set ARGS env var to override default script args (without --max-attempts)

set -u -o pipefail

INSTANCES="${1:-3}"
BATCH_ATTEMPTS="${2:-10}"
BATCHES="${3:-0}"
# Default args: headless, ephemeral profile; we append --max-attempts per batch
ARGS=${ARGS:-"--headless --ephemeral --disable-webspeech"}

# Rotation settings
LOG_MAX_BYTES=${LOG_MAX_BYTES:-5242880}     # 5 MB for per-instance logs
LOG_KEEP=${LOG_KEEP:-5}
METRICS_MAX_BYTES=${METRICS_MAX_BYTES:-104857600}  # 100 MB for metrics
METRICS_KEEP=${METRICS_KEEP:-10}

mkdir -p metrics

# Helper: choose and set a PIA region, then reconnect
choose_and_set_region() {
  if ! command -v piactl >/dev/null 2>&1; then
    echo "piactl not found; skipping initial PIA region set." >&2
    return 0
  fi
  if [[ "${DRY_RUN_PIACTL:-0}" == "1" ]]; then
    echo "[DRY RUN] Would set initial PIA region and reconnect" >&2
    return 0
  fi
  local -a PIA_US_REGIONS=(
    us-east us-west us-california us-texas us-florida
    us-new-york us-chicago us-atlanta us-denver us-seattle
    us-las-vegas us-silicon-valley us-houston us-washington-dc
    us-ohio us-michigan us-missouri us-indiana us-iowa
    us-wisconsin us-baltimore us-wilmington us-new-hampshire
    us-connecticut us-maine us-pennsylvania us-rhode-island
    us-vermont us-montana us-massachusetts us-nebraska
    us-new-mexico us-north-dakota us-wyoming us-alaska
    us-minnesota us-alabama us-oregon us-south-dakota
    us-idaho us-kentucky us-oklahoma us-south-carolina
    us-mississippi us-north-carolina us-kansas us-virginia
    us-west-virginia us-tennessee us-arkansas us-louisiana
    us-honolulu us-salt-lake-city
  )
  local desired="${PIA_REGION:-}"
  if [[ -z "$desired" ]]; then
    desired=${PIA_US_REGIONS[$RANDOM % ${#PIA_US_REGIONS[@]}]}
  fi
  echo "Setting initial PIA region to: $desired"
  piactl set region "$desired" >/dev/null 2>&1 || true
  piactl disconnect >/dev/null 2>&1 || true
  sleep 1
  piactl connect >/dev/null 2>&1 || true
  echo "Waiting for VPN connection after initial set..."
  for i in {1..30}; do
    state=$(piactl get connectionstate 2>/dev/null || echo "")
    if [[ "$state" == "Connected" ]]; then
      ip=$(piactl get vpnip 2>/dev/null || echo "")
      current_region=$(piactl get region 2>/dev/null || echo "")
      echo "Connected. Region: ${current_region:-unknown} | VPN IP: $ip"
      return 0
    fi
    sleep 1
  done
  echo "Warning: VPN connection timeout during initial region set." >&2
  return 0
}

# On script start, ensure region is explicitly set (avoid 'auto')
if command -v piactl >/dev/null 2>&1; then
  current_region=$(piactl get region 2>/dev/null | tr -d '\r\n' || true)
  if [[ -z "$current_region" || "$current_region" == "auto" || "${PIA_SET_AT_START:-1}" == "1" ]]; then
    choose_and_set_region
  fi
fi

# Rotates a file when it exceeds size
rotate_file() {
  local file="$1" max_bytes="$2" keep="$3"
  [[ -f "$file" ]] || return 0
  local size
  size=$(wc -c < "$file" 2>/dev/null || echo 0)
  if [[ "$size" -ge "$max_bytes" ]]; then
    local i
    for (( i=keep; i>=2; i-- )); do
      if [[ -f "${file}.$((i-1))" ]]; then
        mv -f "${file}.$((i-1))" "${file}.${i}" 2>/dev/null || true
      fi
    done
    mv -f "$file" "${file}.1" 2>/dev/null || true
    : > "$file"
    echo "Rotated $file" >&2
  fi
}

# Background monitor to rotate the metrics file periodically
monitor_metrics() {
  local file="$1"
  while true; do
    rotate_file "$file" "$METRICS_MAX_BYTES" "$METRICS_KEEP"
    sleep 5
  done
}

# Rotate PIA region to a random US region after each batch
rotate_pia_region_batch() {
  if ! command -v piactl >/dev/null 2>&1; then
    echo "piactl not found; skipping PIA rotation." >&2
    return 0
  fi
  if [[ "${DRY_RUN_PIACTL:-0}" == "1" ]]; then
    echo "[DRY RUN] Would rotate PIA region to a random US region" >&2
    return 0
  fi
  local -a PIA_US_REGIONS=(
    us-east us-west us-california us-texas us-florida
    us-new-york us-chicago us-atlanta us-denver us-seattle
    us-las-vegas us-silicon-valley us-houston us-washington-dc
    us-ohio us-michigan us-missouri us-indiana us-iowa
    us-wisconsin us-baltimore us-wilmington us-new-hampshire
    us-connecticut us-maine us-pennsylvania us-rhode-island
    us-vermont us-montana us-massachusetts us-nebraska
    us-new-mexico us-north-dakota us-wyoming us-alaska
    us-minnesota us-alabama us-oregon us-south-dakota
    us-idaho us-kentucky us-oklahoma us-south-carolina
    us-mississippi us-north-carolina us-kansas us-virginia
    us-west-virginia us-tennessee us-arkansas us-louisiana
    us-honolulu us-salt-lake-city
  )
  local current
  current=$(piactl get region 2>/dev/null || echo "")
  local chosen=""
  for _ in {1..10}; do
    local cand=${PIA_US_REGIONS[$RANDOM % ${#PIA_US_REGIONS[@]}]}
    if [[ "$cand" != "$current" ]]; then
      chosen="$cand"; break
    fi
  done
  if [[ -z "$chosen" ]]; then
    chosen=${PIA_US_REGIONS[$RANDOM % ${#PIA_US_REGIONS[@]}]}
  fi
  echo "Rotating PIA region to: $chosen (previous: ${current:-unknown})"
  if ! piactl set region "$chosen" >/dev/null 2>&1; then
    echo "Failed to set PIA region; skipping." >&2
    return 0
  fi
  piactl disconnect >/dev/null 2>&1 || true
  sleep 1
  piactl connect >/dev/null 2>&1 || true
  echo "Waiting for VPN connection..."
  for i in {1..30}; do
    state=$(piactl get connectionstate 2>/dev/null || echo "")
    if [[ "$state" == "Connected" ]]; then
      ip=$(piactl get vpnip 2>/dev/null || echo "")
      echo "Connected. VPN IP: $ip"
      return 0
    fi
    sleep 1
  done
  echo "Warning: VPN connection timeout after rotation." >&2
  return 0
}

START_TS=$(date +%s)

# In TEST_MODE, default to 2 batches if not specified
if [[ "${TEST_MODE:-0}" == "1" && "$BATCHES" == "0" ]]; then
  BATCHES=${TEST_BATCHES:-2}
fi

TEST_MAX_SECONDS=${TEST_MAX_SECONDS:-0}

batch=0
while true; do
  batch=$((batch+1))
  # Stop if we've already completed requested batches
  if [[ "$BATCHES" != "0" && "$batch" -gt "$BATCHES" ]]; then
    break
  fi
  STAMP=$(date +%Y%m%d_%H%M%S)
  METRICS_FILE="metrics/metrics_${STAMP}_batch${batch}.jsonl"
  # Determine current PIA region for this batch (best-effort)
  BATCH_REGION="unknown"
  if command -v piactl >/dev/null 2>&1; then
    BATCH_REGION=$(piactl get region 2>/dev/null | tr -d '\r' | tr -d '\n')
    [[ -z "$BATCH_REGION" ]] && BATCH_REGION="unknown"
  fi
  echo "\n=== Batch ${batch} ==="
  echo "Instances: $INSTANCES | Attempts per instance: $BATCH_ATTEMPTS"
  echo "Metrics file: $METRICS_FILE | Region: $BATCH_REGION"
  echo "Launching $INSTANCES instance(s) with args: $ARGS --max-attempts $BATCH_ATTEMPTS"

  if [[ "${TEST_MODE:-0}" == "1" ]]; then
    echo "TEST_MODE=1: Skipping instance launch; simulating batch work..."
    sleep 1
  else
    pids=()
    # Launch instances for this batch
    for i in $(seq 1 "$INSTANCES"); do
      echo "Starting instance $i/$INSTANCES..."
      LOG_MAX_BYTES="$LOG_MAX_BYTES" LOG_KEEP="$LOG_KEEP" \
        python3 seccompare_click.py $ARGS --max-attempts "$BATCH_ATTEMPTS" \
          --metrics-file "$METRICS_FILE" --instance-id "batch${batch}-inst${i}" --batch-region "$BATCH_REGION" \
          > >(./rotating_log.sh "instance_${i}.log") 2>&1 &
      pids+=($!)
      sleep 0.2
    done

    echo "Started ${#pids[@]} instance(s): ${pids[*]}"

    # Start metrics monitor
    watcher_pid=""
    monitor_metrics "$METRICS_FILE" &
    watcher_pid=$!

    # Cleanup handler for Ctrl-C during this batch
    cleanup() {
      echo "Stopping all instances..."
      for pid in "${pids[@]}"; do
        kill "$pid" 2>/dev/null || true
      done
      if [[ -n "$watcher_pid" ]]; then
        kill "$watcher_pid" 2>/dev/null || true
      fi
      wait
      exit 0
    }
    trap cleanup INT TERM

    # Wait for batch to complete
    wait

    # Stop metrics monitor
    if [[ -n "$watcher_pid" ]]; then
      kill "$watcher_pid" 2>/dev/null || true
    fi
  fi

  echo "Batch ${batch} complete. Metrics saved to: $METRICS_FILE"

  # Rotate PIA region after batch
  rotate_pia_region_batch
  
  # Small pause between batches
  sleep 1

  # In TEST_MODE, optionally stop after max seconds
  if [[ "${TEST_MODE:-0}" == "1" && "$TEST_MAX_SECONDS" -gt 0 ]]; then
    now=$(date +%s)
    elapsed=$((now - START_TS))
    if [[ "$elapsed" -ge "$TEST_MAX_SECONDS" ]]; then
      echo "TEST_MODE: Reached time limit (${elapsed}s ≥ ${TEST_MAX_SECONDS}s). Exiting."
      break
    fi
  fi
done

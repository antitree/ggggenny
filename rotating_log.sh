#!/usr/bin/env bash
# rotating_log.sh BASE_FILE
# Reads from stdin and appends to BASE_FILE, rotating when size exceeds LOG_MAX_BYTES.

set -euo pipefail

BASE_FILE=${1:?"usage: rotating_log.sh BASE_FILE"}
MAX_BYTES=${LOG_MAX_BYTES:-10485760}   # 10 MB default
KEEP=${LOG_KEEP:-5}

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
  fi
}

mkdir -p "$(dirname "$BASE_FILE")" || true

buffer=""
lines=0
while IFS= read -r line; do
  # Rotate if needed before appending the next chunk
  rotate_file "$BASE_FILE" "$MAX_BYTES" "$KEEP"
  printf '%s\n' "$line" >> "$BASE_FILE"
  lines=$((lines+1))
  # Periodically check size as well, cheap operation
  if (( lines % 50 == 0 )); then
    rotate_file "$BASE_FILE" "$MAX_BYTES" "$KEEP"
  fi
done

exit 0


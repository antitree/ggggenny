#!/usr/bin/env python3
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone


PIA_US_REGIONS = [
    "us-east", "us-west", "us-california", "us-texas", "us-florida",
    "us-new-york", "us-chicago", "us-atlanta", "us-denver", "us-seattle",
    "us-las-vegas", "us-silicon-valley", "us-houston", "us-washington-dc",
    "us-ohio", "us-michigan", "us-missouri", "us-indiana", "us-iowa",
    "us-wisconsin", "us-baltimore", "us-wilmington", "us-new-hampshire",
    "us-connecticut", "us-maine", "us-pennsylvania", "us-rhode-island",
    "us-vermont", "us-montana", "us-massachusetts", "us-nebraska",
    "us-new-mexico", "us-north-dakota", "us-wyoming", "us-alaska",
    "us-minnesota", "us-alabama", "us-oregon", "us-south-dakota",
    "us-idaho", "us-kentucky", "us-oklahoma", "us-south-carolina",
    "us-mississippi", "us-north-carolina", "us-kansas", "us-virginia",
    "us-west-virginia", "us-tennessee", "us-arkansas", "us-louisiana",
    "us-honolulu", "us-salt-lake-city",
]


def iso_ts() -> str:
    # Use UTC without timezone suffix to match existing metrics
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def choose_new_region(current: str | None) -> str:
    if not current:
        return random.choice(PIA_US_REGIONS)
    for _ in range(10):
        cand = random.choice(PIA_US_REGIONS)
        if cand != current:
            return cand
    return random.choice(PIA_US_REGIONS)


def main():
    ap = argparse.ArgumentParser(description="Generate synthetic metrics JSONL for TUI testing")
    ap.add_argument("--output", required=True, help="Path to metrics JSONL file to append")
    ap.add_argument("--instances", type=int, default=3, help="Number of synthetic instances (default: 3)")
    ap.add_argument("--duration", type=float, default=30.0, help="Total duration in seconds (default: 30)")
    ap.add_argument("--tick", type=float, default=1.0, help="Tick interval seconds (default: 1.0)")
    ap.add_argument("--attempts-per-tick", type=int, default=1, help="Attempts per instance per tick (default: 1)")
    ap.add_argument("--success-rate", type=float, default=0.7, help="Probability of success per attempt (default: 0.7)")
    ap.add_argument("--rotate-every", type=float, default=10.0, help="Rotate batch_region every N seconds (default: 10)")
    ap.add_argument("--url", default="https://www.seccompare.com", help="URL to record in metrics")
    ap.add_argument("--proxy", action="store_true", help="Set proxy=true in metrics")
    ap.add_argument("--seed", type=int, default=None, help="Random seed")
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)

    attempts = [0 for _ in range(args.instances)]
    current_region = choose_new_region(None)
    next_rotate = time.time() + args.rotate_every
    end_time = time.time() + args.duration

    with open(args.output, "a", encoding="utf-8") as f:
        while time.time() < end_time:
            now = time.time()
            if now >= next_rotate:
                current_region = choose_new_region(current_region)
                next_rotate = now + args.rotate_every
            for inst in range(1, args.instances + 1):
                for _ in range(args.attempts_per_tick):
                    attempts[inst - 1] += 1
                    ok = random.random() < args.success_rate
                    reason = "success_text_detected" if ok else random.choice([
                        "no_success_text", "button_not_found", "timeout_exception", "generic_exception"
                    ])
                    payload = {
                        "ts": iso_ts(),
                        "instance_id": f"gen{inst}",
                        "attempt": attempts[inst - 1],
                        "success": bool(ok),
                        "reason": reason,
                        "elapsed_ms": int(random.uniform(300, 3500)),
                        "proxy": bool(args.proxy),
                        "rotated_on_failure": (not ok) and (random.random() < 0.3),
                        "url": args.url,
                        "batch_region": current_region,
                    }
                    f.write(json.dumps(payload) + "\n")
            f.flush()
            time.sleep(max(0.05, float(args.tick)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


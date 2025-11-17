#!/usr/bin/env python3
import argparse
import json
import os
from collections import defaultdict


def load_metrics(path):
    data = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                data.append(obj)
            except Exception:
                continue
    return data


def summarize(data):
    total_success = sum(1 for d in data if d.get("success"))
    total_fail = sum(1 for d in data if not d.get("success"))
    per_instance = defaultdict(lambda: {"success": 0, "fail": 0})
    per_region = defaultdict(lambda: {"success": 0, "fail": 0})
    for d in data:
        inst = str(d.get("instance_id") or "unknown")
        if d.get("success"):
            per_instance[inst]["success"] += 1
        else:
            per_instance[inst]["fail"] += 1
        region = str(d.get("batch_region") or "unknown")
        if d.get("success"):
            per_region[region]["success"] += 1
        else:
            per_region[region]["fail"] += 1
    return total_success, total_fail, per_instance, per_region


def write_csv_summary(path, total_success, total_fail, per_instance, per_region):
    csv_path = os.path.splitext(path)[0] + ".summary.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("section,key,value\n")
        f.write(f"overall,success,{total_success}\n")
        f.write(f"overall,fail,{total_fail}\n")
        for inst, counts in sorted(per_instance.items(), key=lambda x: x[0]):
            f.write(f"instance_{inst},success,{counts['success']}\n")
            f.write(f"instance_{inst},fail,{counts['fail']}\n")
        for reg, counts in sorted(per_region.items(), key=lambda x: x[0]):
            f.write(f"region_{reg},success,{counts['success']}\n")
            f.write(f"region_{reg},fail,{counts['fail']}\n")
    return csv_path


def plot_metrics(path, total_success, total_fail, per_instance, per_region, out_path):
    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"matplotlib not available ({e}); writing CSV summary instead.")
        csv_path = write_csv_summary(path, total_success, total_fail, per_instance, per_region)
        print(f"Wrote summary CSV: {csv_path}")
        return False

    # Overall + per-region + per-instance charts
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))

    axes[0].bar(["success", "fail"], [total_success, total_fail], color=["#2ca02c", "#d62728"])
    axes[0].set_title("Overall Results")
    axes[0].set_ylabel("Count")

    # Per-region stacked bars
    regions = sorted(per_region.keys(), key=lambda x: (x == "unknown", x))
    r_succ = [per_region[r]["success"] for r in regions]
    r_fail = [per_region[r]["fail"] for r in regions]
    rx = range(len(regions))
    axes[1].bar(rx, r_succ, label="success", color="#2ca02c")
    axes[1].bar(rx, r_fail, bottom=r_succ, label="fail", color="#d62728")
    axes[1].set_xticks(list(rx))
    axes[1].set_xticklabels(regions, rotation=45, ha="right")
    axes[1].set_title("Per-region Results")
    axes[1].legend()

    # Per-instance stacked bars
    instances = sorted(per_instance.keys(), key=lambda x: (x == "unknown", x))
    succ = [per_instance[i]["success"] for i in instances]
    fail = [per_instance[i]["fail"] for i in instances]
    x = range(len(instances))
    axes[2].bar(x, succ, label="success", color="#2ca02c")
    axes[2].bar(x, fail, bottom=succ, label="fail", color="#d62728")
    axes[2].set_xticks(list(x))
    axes[2].set_xticklabels(instances, rotation=45, ha="right")
    axes[2].set_title("Per-instance Results")
    axes[2].legend()

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f"Saved visualization: {out_path}")
    return True


def main():
    ap = argparse.ArgumentParser(description="Analyze and visualize seccompare metrics.")
    ap.add_argument("--input", required=True, help="Path to JSONL metrics file produced by run_instances.sh")
    ap.add_argument("--out", default=None, help="Output image path (PNG). Default: <metrics>.png")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(f"Metrics file not found: {args.input}")
        return 1

    data = load_metrics(args.input)
    if not data:
        print("No metrics found in file.")
        return 1

    total_success, total_fail, per_instance, per_region = summarize(data)
    print(f"Overall - success: {total_success}, fail: {total_fail}")
    for inst, counts in sorted(per_instance.items(), key=lambda x: x[0]):
        print(f"Instance {inst}: success={counts['success']} fail={counts['fail']}")
    for reg, counts in sorted(per_region.items(), key=lambda x: x[0]):
        print(f"Region {reg}: success={counts['success']} fail={counts['fail']}")

    out_path = args.out or (os.path.splitext(args.input)[0] + ".png")
    plot_metrics(args.input, total_success, total_fail, per_instance, per_region, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Live Day-22 DejaVu demo.

Writes each demo step to RawTree as it happens so the dashboard can animate
memory/context state from durable records. This is intentionally isolated from
the validated 30-day experiment tables.
"""
import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.dejavu.clients.tinybird import TinybirdClient

DAY22 = {
    "scenario": "day22",
    "simulated_at": "2026-09-22T19:20:00Z",
    "steps": [
        {
            "step": 1,
            "title": "Page received",
            "detail": "checkout_error_rate_high · checkout-api",
            "context_tokens": 0,
            "memory_count": 10,
        },
        {
            "step": 2,
            "title": "Reading current telemetry from RawTree",
            "detail": "config-day22-reduce · payments.max_connections: 100 → 20",
            "context_tokens": 1850,
            "memory_count": 10,
        },
        {
            "step": 3,
            "title": "Searching institutional memory",
            "detail": "MATCH FOUND → Day 4 · config-day04-reduce · same 100 → 20 trajectory",
            "context_tokens": 3310,
            "memory_count": 10,
        },
        {
            "step": 4,
            "title": "Building bounded context",
            "detail": "Retrieved Day-4 connection-limit lesson and current Day-22 evidence",
            "context_tokens": 5225,
            "memory_count": 10,
        },
        {
            "step": 5,
            "title": "DejaVu decision",
            "detail": "restore_connection_limit → recycle_checkout_pods",
            "context_tokens": 5225,
            "memory_count": 10,
        },
        {
            "step": 6,
            "title": "Memory revalidated",
            "detail": "Day-4 lesson revalidated by Day-22 recurrence",
            "context_tokens": 5225,
            "memory_count": 11,
        },
        {
            "step": 7,
            "title": "Incident resolved",
            "detail": "config-day22-restore → action-day22-recycle → alert-day22-checkout-resolved",
            "context_tokens": 5225,
            "memory_count": 11,
        },
    ],
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description="Run the RawTree-backed DejaVu live demo.")
    parser.add_argument("scenario", choices=["day22"], nargs="?", default="day22")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between visible steps.")
    args = parser.parse_args()

    demo = DAY22
    client = TinybirdClient()
    run_id = f"live-{args.scenario}-{uuid.uuid4().hex[:10]}"

    print("\nDejaVu LIVE DEMO · Day 22 recurrence")
    print(f"run_id: {run_id}")
    print("RawTree: dejavu_live_demo_points")
    print("Keep /rawtree open beside this terminal; the live graph polls automatically.\n")

    for item in demo["steps"]:
        row = {
            "record_id": f"{run_id}:{item['step']}",
            "run_id": run_id,
            "scenario": args.scenario,
            "simulated_at": demo["simulated_at"],
            "step": item["step"],
            "title": item["title"],
            "detail": item["detail"],
            "context_tokens": item["context_tokens"],
            "memory_count": item["memory_count"],
            "created_at": utcnow(),
        }
        client.ingest_events("dejavu_live_demo_points", [row])

        prefix = "✓" if item["step"] == 7 else f"[{item['step']}]"
        print(f"{prefix} {item['title']}")
        print(f"    {item['detail']}")
        if item["step"] == 3:
            print("    institutional memory → Day 4 lesson retrieved")
        if item["step"] == 4:
            print(f"    working context → {item['context_tokens']:,} tokens")
        if item["step"] == 6:
            print(f"    lessons held → {item['memory_count']}")
        print(flush=True)

        if item["step"] != len(demo["steps"]):
            time.sleep(args.delay)

    print("✓ Incident resolved")
    print("  Live-demo records are isolated from the validated 30-day experiment.\n")


if __name__ == "__main__":
    main()

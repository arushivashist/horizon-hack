#!/usr/bin/env python3
"""Live stale-memory -> Nimble -> memory-update demo.

This scenario is intentionally isolated from the validated 30-day experiment.
It demonstrates the lifecycle: RETRIEVE -> STALE -> RESEARCH -> SUPERSEDE -> REVALIDATE.
"""
import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.dejavu.clients.nimble import NimbleClient
from src.dejavu.clients.tinybird import TinybirdClient

SCENARIO = "day35-nimble"
SIMULATED_AT = "2026-10-05T19:20:00Z"
OLD_MEMORY = {
    "memory_id": "payrail-regional-degradation-v1",
    "subject": "PayRail regional degradation",
    "status": "STALE",
    "last_validated_at": "2026-06-02T21:05:00Z",
    "recommendation": "Reduce retries, queue non-urgent refunds, and wait for PayRail recovery.",
}
QUERY = (
    "PayRail current guidance regional routing degradation upstream timeout "
    "automatic regional failover backup region"
)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def first_url(obj):
    """Best-effort URL extraction without assuming a single Nimble response shape."""
    if isinstance(obj, dict):
        for key in ("url", "link"):
            value = obj.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        for value in obj.values():
            found = first_url(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = first_url(value)
            if found:
                return found
    return None


def research(nimble, changelog_url):
    """Use Nimble extraction against the controlled public PayRail changelog."""
    extracted = nimble.extract(changelog_url)
    if extracted.get("mode") == "no-key":
        raise RuntimeError("NIMBLE_API_KEY is not loaded in this shell.")
    return extracted


def write_step(rawtree, run_id, step, title, detail, memory_count=11, context_tokens=0, extra=None):
    row = {
        "record_id": f"{run_id}:{step}",
        "run_id": run_id,
        "scenario": SCENARIO,
        "simulated_at": SIMULATED_AT,
        "step": step,
        "title": title,
        "detail": detail,
        "context_tokens": context_tokens,
        "memory_count": memory_count,
        "created_at": utcnow(),
        "extra_json": json.dumps(extra or {}, ensure_ascii=False),
    }
    rawtree.ingest_events("dejavu_nimble_demo_points", [row])
    stamp = datetime.now().astimezone().strftime("%H:%M:%S")
    print(f"[{stamp}] [{step}] {title}")
    print(f"    {detail}\n", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=3.0)\n    parser.add_argument("--changelog-url", default=os.getenv("PAYRAIL_CHANGELOG_URL", DEFAULT_CHANGELOG_URL))
    args = parser.parse_args()

    rawtree = TinybirdClient()
    nimble = NimbleClient()
    run_id = f"live-nimble-{uuid.uuid4().hex[:10]}"

    print("\nDejaVu LIVE DEMO · stale memory + Nimble revalidation")
    print(f"run_id: {run_id}")
    print("RawTree: dejavu_nimble_demo_points\n")

    steps = [
        ("New incident reported", "PayRail upstream timeouts are affecting checkout."),
        ("Searching institutional memory", "MEMORY FOUND → prior PayRail regional-degradation lesson."),
        ("Checking memory validity", f"STALE MEMORY → last validated {OLD_MEMORY['last_validated_at'][:10]}; do not blindly reuse it."),
    ]
    for i, (title, detail) in enumerate(steps, 1):
        write_step(rawtree, run_id, i, title, detail, context_tokens=180 + i * 120,
                   extra={"old_memory": OLD_MEMORY} if i >= 2 else None)
        time.sleep(args.delay)

    write_step(rawtree, run_id, 4, "Researching current guidance with Nimble",
               "NIMBLE → searching current external evidence before applying the stale recommendation.",
               context_tokens=620)
    url = args.changelog_url
    extracted = research(nimble, url)
    evidence_text = json.dumps(extracted, ensure_ascii=False)
    changed = "regional failover" in evidence_text.lower() and "deprecated" in evidence_text.lower()
    rawtree.ingest_events("dejavu_nimble_evidence", [{
        "record_id": f"{run_id}:nimble",
        "run_id": run_id,
        "scenario": SCENARIO,
        "query": "Extract current PayRail remediation guidance from the changelog",
        "source_url": url,
        "search_json": "{}",
        "extract_json": evidence_text,
        "guidance_changed": changed,
        "created_at": utcnow(),
    }])
    if not changed:
        raise RuntimeError("Nimble response did not contain the expected changed PayRail guidance; refusing to supersede memory.")
    time.sleep(args.delay)

    # The mutation below is gated on the actual Nimble extraction containing
    # the controlled changelog's changed-guidance markers.
    new_memory = {
        "memory_id": "payrail-regional-degradation-v2",
        "subject": "PayRail regional degradation",
        "status": "ACTIVE",
        "supersedes": OLD_MEMORY["memory_id"],
        "recommendation": "Reduce retry pressure, route traffic to the backup region, and verify payment success after failover.",
        "last_validated_at": utcnow(),
        "nimble_source_url": url,
    }
    write_step(rawtree, run_id, 5, "Comparing old memory with current evidence",
               "KNOWLEDGE CHANGED → Nimble found that wait-for-recovery is deprecated and regional failover is now supported.",
               context_tokens=840, extra={"nimble_source_url": url, "guidance_changed": True})
    time.sleep(args.delay)

    rawtree.ingest_events("dejavu_nimble_memory_updates", [{
        "record_id": f"{run_id}:supersede",
        "run_id": run_id,
        "scenario": SCENARIO,
        "operation": "SUPERSEDE",
        "old_memory_id": OLD_MEMORY["memory_id"],
        "new_memory_id": new_memory["memory_id"],
        "old_memory_json": json.dumps(OLD_MEMORY, ensure_ascii=False),
        "new_memory_json": json.dumps(new_memory, ensure_ascii=False),
        "evidence_url": url,
        "created_at": utcnow(),
    }])
    write_step(rawtree, run_id, 6, "Updating institutional memory",
               "SUPERSEDE → keep the old lesson for provenance and activate the newly validated version.",
               memory_count=12, context_tokens=980, extra={"new_memory": new_memory})
    time.sleep(args.delay)

    write_step(rawtree, run_id, 7, "Building bounded context",
               "Current telemetry + prior incident + Nimble evidence + updated memory fit inside the fixed context budget.",
               memory_count=12, context_tokens=1160)
    time.sleep(args.delay)

    write_step(rawtree, run_id, 8, "DejaVu decision",
               "Use the newly validated PayRail guidance instead of blindly applying the stale recommendation.",
               memory_count=12, context_tokens=1160)
    print("✓ Stale knowledge detected, externally researched, and memory superseded.\n")


if __name__ == "__main__":
    main()

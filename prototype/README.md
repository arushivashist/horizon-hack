# Prototype test harness

Built the morning of Sep 25, 2026 to test the idea on 12 simulated days before the full build.

- `gen.py` writes the simulated store's telemetry, pages and ground truth to `data/`.
- `run.py` runs the agents (`baseline`, `notebook`, `hybrid`) on the same pages and scores them.

```bash
python3 gen.py
uv run --with anthropic --with duckdb python run.py --fake            # plumbing check, no API calls
uv run --with anthropic --with duckdb python run.py --agent hybrid    # needs ANTHROPIC_API_KEY
```

## Results

All runs used claude-opus-5 on the same 12 days (14 pages, 2 real incidents). Each folder holds the scored runs as JSON plus the run log.

- `results/run1/`: baseline vs. notebook. Both got 14/14, but the notebook never saved the day-4 lesson. This run used an earlier notebook memory (whole rewrites under a 2,500-character cap) that isn't in `run.py` anymore.
- `results/run2/`: the same pair, with one-entry memory edits. Both got 14/14; the notebook re-ran its own queries and cost $4.31 against the baseline's $0.92.
- `results/run3/`: the hybrid agent alone. 14/14 with 50 queries, a largest context of 10.8k tokens, and $1.66.
- `results/run4-safe-memory/`: the safe-memory agent on the same 12 days. 14/14, 4 queries on each incident, $1.99. Only the run log is here; its memory log was overwritten by a later fake-model check.

## Safe memory on the Northstar world

- `safe_memory.py` is the combined agent with checked memory writes. Every entry must cite pages the agent closed, nothing is written mid-investigation, instruction-like text and links are refused, sections have slot and size limits, and every attempt goes to an append-only log you can replay.
- `northstar.py` runs that agent, or the baseline with `--agent baseline`, on the Northstar Commerce 30-day mock world from [Cioran123/wallymartdata](https://github.com/Cioran123/wallymartdata). Clone it next to this folder or pass `--world PATH`. The agent never sees `incident_id` or the answer key, and each page is scored against the world's `ground_truth.json`.

```bash
uv run --with anthropic --with duckdb python northstar.py --fake                # no API calls
uv run --with anthropic --with duckdb python northstar.py --env-file PATH       # needs an Anthropic key
```

- `results/northstar-30-day-run1/`: the safe-memory agent on all 30 days (39 pages, 4 incidents). 39/39, including the day-24 look-alike whose old runbook advice is wrong. 200 queries, a largest context of 16,110 tokens, and $6.41.
- `results/northstar-30-day-safe-traced/`: a second safe-memory run with a per-call context trace, used by the dashboard. 39/39, 116 queries, a largest context of 11,564 tokens, $6.07, and 2 queries on the day-22 repeat.
- `results/northstar-30-day-baseline/`: the history-plus-summaries agent on the same 30 days, with a per-call context trace. 39/39 as well, 104 queries, a largest context of 31,784 tokens, and $2.40.

## Dashboard

`build_story.py` turns both 30-day runs into the interactive dashboard at [`docs/experiment-dashboard.html`](../docs/experiment-dashboard.html) (timeline, what each agent did per page, context chart, memory log). `build_dashboard.py` and `dashboard_template.html` are an earlier single-chart version.

```bash
uv run --with anthropic --with duckdb python build_story.py
```

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

# Prototype test harness

Built the morning of Sep 25, 2026 to test the idea on 12 simulated days before the full build.

- `gen.py` writes the simulated store's telemetry, pages and ground truth to `data/`.
- `run.py` runs the agents (`baseline`, `notebook`, `hybrid`) on the same pages and scores them.

```bash
python3 gen.py
uv run --with anthropic --with duckdb python run.py --fake            # plumbing check, no API calls
uv run --with anthropic --with duckdb python run.py --agent hybrid    # needs ANTHROPIC_API_KEY
```

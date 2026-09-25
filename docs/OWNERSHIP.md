# Build Ownership

| Owner piece | Code |
|---|---|
| Tinybird + ingestion | `tinybird/`, `src/dejavu/ingestion/`, `clients/tinybird.py` |
| Liquid + trajectory analysis | `src/dejavu/analysis/`, `clients/liquid.py` |
| Institutional Memory | `src/dejavu/memory/` |
| Nimble freshness/research | `src/dejavu/external/`, `clients/nimble.py` |
| Context Builder + agent | `src/dejavu/context/`, `src/dejavu/agent/` |
| Demo | `src/dejavu/demo/` |

## Integration contract
`telemetry -> ObservationWindow -> classification/matches -> Memory Update -> active memory -> Context Builder -> fixed token budget -> Agent -> Outcome -> Memory Update`.

Tinybird current state is incremental; Liquid is gated/batched; Nimble is TTL-cached; Context Builder enforces the hard memory-token budget.

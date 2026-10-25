# Corrective retrieval demonstration

For example, an initial search finds a retry count but misses the delay. An application-approved second query can retrieve that delay. The engine keeps useful evidence, checks access again, then assesses the original question.

Run from the checkout after the frozen core setup and TypeScript build described in [development](../docs/development.md):

```sh
uv run --project packages/python --frozen python tools/check_corrective.py --show-results
```

This executes both native engines and compares complete results across the shared CR-r1 cases. The `demonstration` output contains a sufficient targeted recovery, a partial no-plan result, an insufficient empty search, transient provider failure and permanent authorization failure. Each successful result includes evidence, citations, limitations, usage and a stop reason. Operational failures have typed error codes; they do not become insufficient evidence.

The injected backend and planner are intentionally synthetic. No database, API key or paid call is needed. These cases explain execution and failure handling; they do not measure a model's quality. The clean artifact checkpoint repeats the same engine cases with installed wheel and npm modules outside the checkout.

Inspect `targeted-recovery` and `repeated-candidates`: the former can become sufficient, while the latter stops when another search repeats the same candidates. Practice: reduce the recovery case's candidate budget and explain why the result keeps an explicit limitation. Do not change trusted filters to recover more evidence.

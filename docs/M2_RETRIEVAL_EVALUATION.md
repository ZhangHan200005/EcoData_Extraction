# M2 first-slice retrieval evaluation

Recorded: 2026-08-15

## Purpose

This report verifies that the M2 retrieval contract can run the same versioned
queries through different vector backends and emit comparable metrics,
diagnostics, version metadata, and timing. It is a contract-scale fixture, not
evidence that a neural model improves retrieval.

## Reproduction

From the repository root, with the documented Python environment installed:

```bash
.venv/bin/python -m backend_tests.run_retrieval_fixture
```

The command uses no network access, API key, private paper, or paid service. It
creates a temporary SQLite database and removes it when the report finishes.

## Configuration

- Fixture: `synthetic-retrieval-comparison-v1`
- Fixture file: `backend_tests/fixtures/retrieval_comparison_v1.json`
- Corpus: one synthetic document, four evidence blocks
- Queries: three (`stem_respiration_rate`, `species`, `site_name`)
- Gold: one verified block per query, three total
- K values: 1 and 3
- Retrieval version: `hybrid-configurable-vector-v2`
- Hybrid weights: BM25 0.45, vector similarity 0.35, term coverage 0.15,
  section prior 0.05
- BM25 parameters: `k1=1.5`, `b=0.75`
- Runtime used for the recorded sample: Python 3.9.6

Backends:

| Backend | Model/version | Dimensions | Neural | Intended use |
| --- | --- | ---: | --- | --- |
| `hashing` v1 | `blake2b-character-ngram@2-4gram-v1` | 384 | No | Production offline baseline |
| `fixture-deterministic` v1 | `deterministic-concept-vectors@fixture-v1` | 3 | No | Test-only contract validation |

## Recorded sample

The following values came from one local invocation at
`2026-08-15T14:10:55Z`. Latency is included to verify measurement and report
shape; one tiny fixture run is not a stable performance benchmark.

| Backend | Hit@1 | Recall@1 | MRR | Retrieval elapsed | Mean/query |
| --- | ---: | ---: | ---: | ---: | ---: |
| `hashing` | 1.0000 | 1.0000 | 1.0000 | 4.103165 ms | 1.367722 ms |
| `fixture-deterministic` | 1.0000 | 1.0000 | 1.0000 | 0.549708 ms | 0.183236 ms |

Both reports evaluated three queries and scored 12 query-block pairs. The full
JSON output includes Hit@K, Recall@K, Precision@K, MRR, backend/model metadata,
parameters, evaluation and retrieval timing, and per-query Gold/top block IDs.

## Limitations and next evidence

- The corpus is deliberately tiny and synthetic; perfect fixture scores do not
  imply representative scientific-PDF performance.
- The deterministic backend is not a neural model and its latency must not be
  compared with a real model.
- M2 still requires a selected real model with documented license, download
  size, privacy behavior, and runtime requirements.
- M2 still requires persistent vector caching keyed by document hash, block ID,
  normalized-text hash, backend, model, and model version.
- A real baseline-versus-neural comparison must reuse a broader frozen Gold set
  before any quality-improvement claim is published.

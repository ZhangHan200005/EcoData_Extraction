# M2 retrieval evaluation history

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

After installing the optional local runtime, include the real pinned model:

```bash
.venv/bin/python -m pip install -e ".[neural]"
.venv/bin/python -m backend_tests.run_retrieval_fixture \
  --include-neural --model-cache data/models
```

After the first download, add `--local-files-only` to prove the evaluation can
run without network access.

## Configuration

- Fixture: `synthetic-retrieval-comparison-v1`
- Fixture file: `backend_tests/fixtures/retrieval_comparison_v1.json`
- Corpus: one synthetic document, four evidence blocks
- Queries: three (`stem_respiration_rate`, `species`, `site_name`)
- Gold: one verified block per query, three total
- K values: 1 and 3
- Current retrieval version: `hybrid-neural-embedding-v4`
- Hybrid weights: BM25 0.45, vector similarity 0.35, term coverage 0.15,
  section prior 0.05
- BM25 parameters: `k1=1.5`, `b=0.75`
- Original baseline runtime: Python 3.9.6
- Neural validation runtime: Python 3.13.13 on Apple Silicon CPU

Backends:

| Backend | Model/version | Dimensions | Neural | Intended use |
| --- | --- | ---: | --- | --- |
| `hashing` v1 | `blake2b-character-ngram@2-4gram-v1` | 384 | No | Production offline baseline |
| `fixture-deterministic` v1 | `deterministic-concept-vectors@fixture-v1` | 3 | No | Test-only contract validation |
| `sentence-transformers` `multilingual-e5-v1` | `intfloat/multilingual-e5-small@614241f622f53c4eeff9890bdc4f31cfecc418b3` | 384 | Yes | Optional local semantic backend |

## First-slice recorded sample

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

## Persistent-cache slice

The current report additionally includes a content/version-addressed SQLite
cache. In one local run at `2026-08-15T16:15:28Z`, each backend produced four
cold misses/writes on the first query and eight warm hits across the next two
queries. The hashing report recorded 9.481918 ms total retrieval time and the
test-only deterministic report recorded 6.547917 ms. These timings verify the
instrumentation only; the fixture is too small for performance conclusions.

The implementation initially opened one SQLite connection per block. A local
diagnostic run exposed that overhead, so the final design batches all cache keys
through one read connection and one `executemany` write. The correctness tests
assert hit/miss behavior rather than unstable wall-clock thresholds.

## Pinned neural slice

The optional runtime pins Sentence Transformers 5.5.1, Transformers 5.15.0,
and PyTorch 2.13.0. The downloaded model cache occupied 470 MB (28 files) in
the recorded local environment. The
[model card](https://huggingface.co/intfloat/multilingual-e5-small) declares an
MIT license. The backend applies the model-required
`query: ` and `passage: ` prefixes, batches all cold passage vectors, and L2
normalizes every output. Automated tests replace the model object and never
download weights.

A local-cache-only invocation at `2026-08-15T16:53:01Z` produced:

| Backend | Hit@1 | Recall@1 | MRR | Retrieval elapsed | Mean/query |
| --- | ---: | ---: | ---: | ---: | ---: |
| `hashing` | 1.0000 | 1.0000 | 1.0000 | 5.724709 ms | 1.908236 ms |
| `multilingual-e5-small` | 1.0000 | 1.0000 | 1.0000 | 5160.129207 ms | 1720.043069 ms |

For E5, the first cold query encoded four passages and included local model
initialization (5132.370791 ms). The next two queries reused all four cached
passage vectors and took 13.743916 ms and 14.0145 ms respectively. A separate
first-download invocation took 22320.161417 ms total retrieval time. These are
single-machine instrumentation samples, not stable benchmarks.

## Limitations and next evidence

- The corpus is deliberately tiny and synthetic; perfect fixture scores do not
  imply representative scientific-PDF performance.
- The deterministic backend is not a neural model and its latency must not be
  compared with a real model.
- The real baseline-versus-neural comparison currently has only three queries
  from one synthetic document. Both systems score perfectly, so there is no
  evidence of a neural quality improvement.
- A broader frozen Gold set spanning multiple papers, languages, paraphrases,
  and hard negatives is required before any quality-improvement claim.
- CPU cold-start and representative-corpus throughput still need measurement;
  the current SQLite cache avoids repeated passage encoding but is not ANN.

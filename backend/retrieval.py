"""Auditable hybrid evidence retrieval with exposed score components."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

from .schemas import (
    BlockRecord,
    EmbeddingCacheKey,
    ProjectSpec,
    RetrievalBackendMetadata,
    RetrievalCacheStats,
    RetrievalHit,
)


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9₂⁻−-]*|\d+(?:\.\d+)?|[\u4e00-\u9fff]+")
EMBEDDING_CACHE_KEY_VERSION = "embedding-cache-key-v1"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_RE.findall(normalize(text)):
        if re.fullmatch(r"[\u4e00-\u9fff]+", match):
            tokens.extend(
                match[index : index + 2]
                for index in range(max(1, len(match) - 1))
            )
            if len(match) <= 6:
                tokens.append(match)
        else:
            tokens.append(match)
    return [token for token in tokens if token.strip()]


class EmbeddingBackend(Protocol):
    """Minimal contract shared by baseline and neural encoders."""

    @property
    def metadata(self) -> RetrievalBackendMetadata: ...

    @property
    def parameters(self) -> dict[str, Any]: ...

    @property
    def runtime_status(self) -> dict[str, Any]: ...

    def encode_query(self, text: str) -> list[float]: ...

    def encode_passages(self, texts: list[str]) -> list[list[float]]: ...


def embedding_cache_key(
    document_sha256: str,
    block: BlockRecord,
    metadata: RetrievalBackendMetadata,
    parameters: dict[str, Any],
) -> EmbeddingCacheKey:
    canonical_parameters = json.dumps(
        parameters,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    identity = {
        "cache_key_version": EMBEDDING_CACHE_KEY_VERSION,
        "document_sha256": document_sha256,
        "block_id": block.block_id,
        "normalized_text_sha256": hashlib.sha256(
            normalize(block.text).encode("utf-8")
        ).hexdigest(),
        "backend": metadata.backend,
        "backend_version": metadata.backend_version,
        "model": metadata.model,
        "model_version": metadata.model_version,
        "dimensions": metadata.dimensions,
        "parameters_sha256": hashlib.sha256(
            canonical_parameters.encode("utf-8")
        ).hexdigest(),
    }
    canonical_identity = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return EmbeddingCacheKey(
        cache_key=hashlib.sha256(
            canonical_identity.encode("utf-8")
        ).hexdigest(),
        **identity,
    )


class EmbeddingVectorCache(Protocol):
    def get_embedding_vectors(
        self, keys: list[EmbeddingCacheKey]
    ) -> dict[str, list[float]]: ...

    def save_embedding_vectors(
        self, records: list[tuple[EmbeddingCacheKey, list[float]]]
    ) -> None: ...


class HashingEmbeddingBackend:
    """Dependency-free character n-gram baseline; explicitly non-neural."""

    def __init__(
        self,
        dimensions: int = 384,
        ngram_widths: tuple[int, ...] = (2, 3, 4),
    ) -> None:
        self.dimensions = dimensions
        self.ngram_widths = ngram_widths

    @property
    def metadata(self) -> RetrievalBackendMetadata:
        return RetrievalBackendMetadata(
            backend="hashing",
            backend_version="v1",
            model="blake2b-character-ngram",
            model_version="2-4gram-v1",
            dimensions=self.dimensions,
            is_neural=False,
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "dimensions": self.dimensions,
            "ngram_widths": list(self.ngram_widths),
            "normalization": "l2",
        }

    @property
    def runtime_status(self) -> dict[str, Any]:
        return {
            "ready": True,
            "dependency": "python-standard-library",
            "dependency_version": "builtin",
        }

    def _encode(self, text: str) -> list[float]:
        compact = re.sub(r"\s+", " ", normalize(text))
        vector = [0.0] * self.dimensions
        for width in self.ngram_widths:
            for index in range(max(0, len(compact) - width + 1)):
                gram = compact[index : index + width]
                digest = hashlib.blake2b(
                    gram.encode("utf-8"), digest_size=8
                ).digest()
                bucket = int.from_bytes(digest, "big") % self.dimensions
                sign = 1.0 if digest[0] & 1 else -1.0
                vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def encode_query(self, text: str) -> list[float]:
        return self._encode(text)

    def encode_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._encode(text) for text in texts]


# Backward-compatible name for callers that used the original baseline class.
HashingEmbedder = HashingEmbeddingBackend


class DisabledEmbeddingBackend:
    """Explicit identity for retrieval strategies that do not use vectors."""

    @property
    def metadata(self) -> RetrievalBackendMetadata:
        return RetrievalBackendMetadata(
            backend="disabled",
            backend_version="v1",
            model="none",
            model_version="none",
            dimensions=1,
            is_neural=False,
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {"enabled": False}

    @property
    def runtime_status(self) -> dict[str, Any]:
        return {"ready": True, "dependency": "none"}

    def encode_query(self, text: str) -> list[float]:
        raise RuntimeError("Vector encoding is disabled for this strategy")

    def encode_passages(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Vector encoding is disabled for this strategy")


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError(
            "Embedding backend returned vectors with inconsistent dimensions"
        )
    return sum(a * b for a, b in zip(left, right))


@dataclass
class BM25Index:
    documents: list[list[str]]
    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self) -> None:
        self.lengths = [len(document) for document in self.documents]
        self.average_length = (
            sum(self.lengths) / len(self.lengths) if self.lengths else 0
        )
        self.frequencies = [Counter(document) for document in self.documents]
        self.document_frequency: Counter[str] = Counter()
        for document in self.documents:
            self.document_frequency.update(set(document))

    def scores(self, query_tokens: list[str]) -> list[float]:
        scores: list[float] = []
        total = len(self.documents)
        for index, frequencies in enumerate(self.frequencies):
            score = 0.0
            length = self.lengths[index]
            for token in set(query_tokens):
                frequency = frequencies[token]
                if not frequency:
                    continue
                df = self.document_frequency[token]
                inverse_document_frequency = math.log(
                    1 + (total - df + 0.5) / (df + 0.5)
                )
                denominator = frequency + self.k1 * (
                    1 - self.b
                    + self.b
                    * (length / self.average_length if self.average_length else 0)
                )
                score += inverse_document_frequency * (
                    frequency * (self.k1 + 1) / denominator
                )
            scores.append(score)
        return scores


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [1.0 if value > 0 else 0.0 for value in values]
    return [(value - low) / (high - low) for value in values]


FIELD_HINTS: dict[str, list[str]] = {
    "species": ["物种", "树种", "species", "taxon", "scientific name"],
    "sample_size": [
        "样本量",
        "样本数",
        "sample size",
        "number of trees",
        "replicates",
        "n =",
    ],
    "site_name": ["站点", "样地", "研究区", "site", "study area", "plot"],
    "latitude": ["纬度", "latitude", "coordinates", "°n", "°s"],
    "longitude": ["经度", "longitude", "coordinates", "°e", "°w"],
    "measurement_method": [
        "测量方法",
        "呼吸室",
        "红外气体分析仪",
        "measurement method",
        "chamber",
        "infrared gas analyzer",
        "irga",
    ],
    "treatment": ["处理", "处理组", "treatment", "girdling", "fertilization"],
    "observation_time": [
        "观测时间",
        "测量时间",
        "measurement date",
        "sampling period",
        "season",
    ],
}


@dataclass(frozen=True)
class RetrievalWeights:
    bm25: float = 0.45
    vector_similarity: float = 0.35
    term_coverage: float = 0.15
    section_prior: float = 0.05

    def __post_init__(self) -> None:
        values = self.as_dict().values()
        if any(value < 0 for value in values):
            raise ValueError("Retrieval weights must be non-negative")
        if not math.isclose(sum(values), 1.0):
            raise ValueError("Retrieval weights must sum to 1.0")

    def as_dict(self) -> dict[str, float]:
        return {
            "bm25": self.bm25,
            "vector_similarity": self.vector_similarity,
            "term_coverage": self.term_coverage,
            "section_prior": self.section_prior,
        }


@dataclass(frozen=True)
class RankedEvidence:
    query: str
    hits: list[RetrievalHit]
    elapsed_ms: float
    cache: RetrievalCacheStats


class EvidenceRetriever:
    def __init__(
        self,
        embedding_backend: EmbeddingBackend | None = None,
        weights: RetrievalWeights | None = None,
        vector_cache: EmbeddingVectorCache | None = None,
    ) -> None:
        self.embedding_backend = embedding_backend or HashingEmbeddingBackend()
        self.weights = weights or RetrievalWeights()
        self.vector_cache = vector_cache

    @property
    def backend_metadata(self) -> RetrievalBackendMetadata:
        return self.embedding_backend.metadata

    @property
    def cache_enabled(self) -> bool:
        return self.vector_cache is not None

    @property
    def backend_runtime_status(self) -> dict[str, Any]:
        return self.embedding_backend.runtime_status

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "weights": self.weights.as_dict(),
            "embedding": self.embedding_backend.parameters,
            "bm25": {"k1": 1.5, "b": 0.75},
            "vector_cache": {
                "enabled": self.cache_enabled,
                "key_version": EMBEDDING_CACHE_KEY_VERSION,
                "storage": "sqlite-json" if self.cache_enabled else "none",
            },
        }

    @staticmethod
    def query_for(field_name: str, spec: ProjectSpec) -> tuple[str, list[str]]:
        for variable in spec.target_variables:
            if variable.name == field_name:
                terms = [variable.label, *variable.synonyms]
                return " ".join(dict.fromkeys(terms)), terms
        for field in [*spec.required_context, *spec.optional_context]:
            if field.name == field_name:
                terms = [field.label, *field.synonyms]
                return " ".join(dict.fromkeys(terms)), terms
        terms = FIELD_HINTS.get(field_name, [field_name.replace("_", " ")])
        return " ".join(terms), terms

    def rank(
        self,
        blocks: list[BlockRecord],
        field_name: str,
        spec: ProjectSpec,
        gold_block_ids: set[str] | None = None,
        document_sha256: str = "",
    ) -> RankedEvidence:
        started_at = perf_counter()
        query, terms = self.query_for(field_name, spec)
        query_tokens = tokenize(query)
        block_tokens = [tokenize(block.text) for block in blocks]
        bm25_raw = BM25Index(block_tokens).scores(query_tokens)
        bm25_scores = _minmax(bm25_raw)
        metadata = self.backend_metadata
        use_vector = self.weights.vector_similarity > 0
        cache_enabled = (
            use_vector
            and self.vector_cache is not None
            and bool(document_sha256)
        )
        cache_hits = cache_misses = cache_writes = 0
        semantic_scores = [0.0] * len(blocks)
        if use_vector:
            query_vector = self.embedding_backend.encode_query(query)
            if len(query_vector) != metadata.dimensions:
                raise ValueError(
                    "Embedding backend vector length does not match its metadata"
                )
            cache_keys = [
                embedding_cache_key(
                    document_sha256,
                    block,
                    metadata,
                    self.embedding_backend.parameters,
                )
                for block in blocks
            ]
            cached_vectors = (
                self.vector_cache.get_embedding_vectors(cache_keys)
                if cache_enabled and self.vector_cache
                else {}
            )
            missing_indices = [
                index
                for index, key in enumerate(cache_keys)
                if key.cache_key not in cached_vectors
            ]
            encoded_missing = self.embedding_backend.encode_passages(
                [blocks[index].text for index in missing_indices]
            )
            if len(encoded_missing) != len(missing_indices):
                raise ValueError(
                    "Embedding backend returned an unexpected passage count"
                )
            encoded_by_index = dict(zip(missing_indices, encoded_missing))
            pending_writes: list[tuple[EmbeddingCacheKey, list[float]]] = []
            block_vectors: list[list[float]] = []
            for index, key in enumerate(cache_keys):
                vector = cached_vectors.get(key.cache_key)
                if vector is None:
                    vector = encoded_by_index[index]
                    if cache_enabled and self.vector_cache:
                        cache_misses += 1
                        pending_writes.append((key, vector))
                else:
                    cache_hits += 1
                if len(vector) != metadata.dimensions:
                    raise ValueError(
                        "Embedding vector length does not match backend metadata"
                    )
                block_vectors.append(vector)
            if pending_writes and self.vector_cache:
                self.vector_cache.save_embedding_vectors(pending_writes)
                cache_writes = len(pending_writes)
            semantic_scores = [
                max(0.0, cosine(query_vector, vector))
                for vector in block_vectors
            ]
        expected_sections = self._expected_sections(field_name)
        gold = gold_block_ids or set()
        hits: list[RetrievalHit] = []
        lowered_terms = [normalize(term) for term in terms if term.strip()]
        for index, block in enumerate(blocks):
            lowered = normalize(block.text)
            matched = [term for term in terms if normalize(term) in lowered]
            lexical_coverage = (
                len({normalize(term) for term in matched})
                / len(set(lowered_terms))
                if lowered_terms
                else 0.0
            )
            section_prior = (
                1.0
                if block.section in expected_sections
                else 0.65
                if block.kind in {"figure_caption", "table_caption"}
                else 0.15
            )
            score = (
                self.weights.bm25 * bm25_scores[index]
                + self.weights.vector_similarity * semantic_scores[index]
                + self.weights.term_coverage * lexical_coverage
                + self.weights.section_prior * section_prior
            )
            hits.append(
                RetrievalHit(
                    rank=0,
                    block=block,
                    score=round(score, 6),
                    score_components={
                        "bm25": round(bm25_scores[index], 6),
                        "semantic": round(semantic_scores[index], 6),
                        "term_coverage": round(lexical_coverage, 6),
                        "section_prior": round(section_prior, 6),
                    },
                    matched_terms=matched,
                    is_gold=block.block_id in gold,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.block.ordinal))
        for rank, hit in enumerate(hits, 1):
            hit.rank = rank
        return RankedEvidence(
            query=query,
            hits=hits,
            elapsed_ms=round((perf_counter() - started_at) * 1000, 6),
            cache=RetrievalCacheStats(
                enabled=cache_enabled,
                hits=cache_hits,
                misses=cache_misses,
                writes=cache_writes,
            ),
        )

    @staticmethod
    def _expected_sections(field_name: str) -> set[str]:
        if field_name in {
            "sample_size",
            "site_name",
            "latitude",
            "longitude",
            "measurement_method",
            "observation_time",
        }:
            return {"methods"}
        if field_name in {"species", "treatment"}:
            return {"methods", "results"}
        return {"results", "methods"}

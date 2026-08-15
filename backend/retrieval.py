"""Auditable hybrid evidence retrieval with exposed score components."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass

from .schemas import BlockRecord, ProjectSpec, RetrievalHit


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9₂⁻−-]*|\d+(?:\.\d+)?|[\u4e00-\u9fff]+")


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


class HashingEmbedder:
    """Dependency-free character n-gram vector baseline for zh/en retrieval."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def encode(self, text: str) -> list[float]:
        compact = re.sub(r"\s+", " ", normalize(text))
        vector = [0.0] * self.dimensions
        for width in (2, 3, 4):
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


def cosine(left: list[float], right: list[float]) -> float:
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


class EvidenceRetriever:
    def __init__(self, dimensions: int = 384) -> None:
        self.embedder = HashingEmbedder(dimensions)

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
    ) -> tuple[str, list[RetrievalHit]]:
        query, terms = self.query_for(field_name, spec)
        query_tokens = tokenize(query)
        block_tokens = [tokenize(block.text) for block in blocks]
        bm25_raw = BM25Index(block_tokens).scores(query_tokens)
        bm25_scores = _minmax(bm25_raw)
        query_vector = self.embedder.encode(query)
        semantic_scores = [
            max(0.0, cosine(query_vector, self.embedder.encode(block.text)))
            for block in blocks
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
                0.45 * bm25_scores[index]
                + 0.35 * semantic_scores[index]
                + 0.15 * lexical_coverage
                + 0.05 * section_prior
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
        return query, hits

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

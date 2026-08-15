from __future__ import annotations

import tempfile
import unittest
from importlib import metadata as importlib_metadata
from pathlib import Path
from unittest.mock import patch

from backend.embedding_backends import (
    MULTILINGUAL_E5_MODEL,
    MULTILINGUAL_E5_REVISION,
    SENTENCE_TRANSFORMERS_VERSION,
    EmbeddingBackendUnavailableError,
    MultilingualE5SmallEmbeddingBackend,
    build_embedding_backend,
)


class FakeVectors(list[list[float]]):
    def tolist(self) -> list[list[float]]:
        return list(self)


class FakeSentenceTransformer:
    def __init__(self) -> None:
        self.encode_calls: list[tuple[list[str], dict]] = []

    def encode(self, texts: list[str], **kwargs: object) -> FakeVectors:
        self.encode_calls.append((texts, kwargs))
        return FakeVectors([[1.0, *([0.0] * 383)] for _ in texts])


class NeuralEmbeddingBackendTests(unittest.TestCase):
    def test_pinned_e5_backend_is_lazy_and_applies_asymmetric_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake_model = FakeSentenceTransformer()
            factory_calls: list[tuple[tuple, dict]] = []

            def factory(*args: object, **kwargs: object) -> FakeSentenceTransformer:
                factory_calls.append((args, kwargs))
                return fake_model

            backend = MultilingualE5SmallEmbeddingBackend(
                Path(directory) / "models",
                batch_size=7,
                device="cpu",
                local_files_only=True,
                model_factory=factory,
            )

            self.assertEqual([], factory_calls)
            self.assertTrue(backend.metadata.is_neural)
            self.assertEqual(MULTILINGUAL_E5_MODEL, backend.metadata.model)
            self.assertEqual(
                MULTILINGUAL_E5_REVISION,
                backend.metadata.model_version,
            )
            self.assertEqual(384, backend.metadata.dimensions)
            self.assertTrue(backend.runtime_status["ready"])

            query = backend.encode_query("  树干   呼吸速率 ")
            passages = backend.encode_passages(
                ["Stem respiration result", "  Alpine   site "]
            )

            self.assertEqual(384, len(query))
            self.assertEqual([384, 384], [len(item) for item in passages])
            self.assertEqual(1, len(factory_calls))
            args, kwargs = factory_calls[0]
            self.assertEqual((MULTILINGUAL_E5_MODEL,), args)
            self.assertEqual(MULTILINGUAL_E5_REVISION, kwargs["revision"])
            self.assertEqual("cpu", kwargs["device"])
            self.assertTrue(kwargs["local_files_only"])
            self.assertFalse(kwargs["trust_remote_code"])
            self.assertEqual(
                ["query: 树干 呼吸速率"],
                fake_model.encode_calls[0][0],
            )
            self.assertEqual(
                [
                    "passage: Stem respiration result",
                    "passage: Alpine site",
                ],
                fake_model.encode_calls[1][0],
            )
            for _, encode_kwargs in fake_model.encode_calls:
                self.assertEqual(7, encode_kwargs["batch_size"])
                self.assertTrue(encode_kwargs["normalize_embeddings"])
                self.assertTrue(encode_kwargs["convert_to_numpy"])
                self.assertFalse(encode_kwargs["show_progress_bar"])

    def test_missing_optional_runtime_fails_without_downloading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = MultilingualE5SmallEmbeddingBackend(Path(directory))
            with patch(
                "backend.embedding_backends.importlib_metadata.version",
                side_effect=importlib_metadata.PackageNotFoundError,
            ):
                with self.assertRaisesRegex(
                    EmbeddingBackendUnavailableError,
                    r"pip install -e",
                ):
                    backend.encode_query("query")

    def test_factory_keeps_hashing_as_default_and_rejects_unknown_names(self) -> None:
        hashing = build_embedding_backend(
            "hashing",
            cache_folder=Path("unused"),
        )

        self.assertEqual("hashing", hashing.metadata.backend)
        self.assertTrue(hashing.runtime_status["ready"])
        neural = build_embedding_backend(
            "multilingual-e5-small",
            cache_folder=Path("models"),
            local_files_only=True,
        )
        self.assertTrue(neural.metadata.is_neural)
        self.assertTrue(neural.parameters["local_files_only"])
        with self.assertRaisesRegex(ValueError, "Unknown retrieval backend"):
            build_embedding_backend(
                "unsupported",
                cache_folder=Path("unused"),
            )

    def test_parameters_record_reproducible_runtime_contract(self) -> None:
        backend = MultilingualE5SmallEmbeddingBackend(Path("models"))

        self.assertEqual(
            SENTENCE_TRANSFORMERS_VERSION,
            backend.parameters["runtime_version"],
        )
        self.assertEqual("query: ", backend.parameters["query_prefix"])
        self.assertEqual("passage: ", backend.parameters["passage_prefix"])
        self.assertNotIn("cache_folder", backend.parameters)


if __name__ == "__main__":
    unittest.main()

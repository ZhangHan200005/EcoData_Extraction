"""Optional local neural embedding backends and their versioned factory."""

from __future__ import annotations

from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Callable

from .retrieval import HashingEmbeddingBackend
from .schemas import RetrievalBackendMetadata


MULTILINGUAL_E5_MODEL = "intfloat/multilingual-e5-small"
MULTILINGUAL_E5_REVISION = (
    "614241f622f53c4eeff9890bdc4f31cfecc418b3"
)
SENTENCE_TRANSFORMERS_VERSION = "5.5.1"
TRANSFORMERS_VERSION = "5.15.0"
TORCH_VERSION = "2.13.0"


def _installed_version(package: str) -> str:
    try:
        return importlib_metadata.version(package)
    except importlib_metadata.PackageNotFoundError:
        return "not-installed"


class EmbeddingBackendUnavailableError(RuntimeError):
    """Raised when a selected optional embedding runtime cannot be loaded."""


class MultilingualE5SmallEmbeddingBackend:
    """Pinned, local Sentence Transformers backend for multilingual retrieval."""

    def __init__(
        self,
        cache_folder: Path,
        *,
        batch_size: int = 32,
        device: str = "cpu",
        local_files_only: bool = False,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("Embedding batch size must be at least 1")
        self.cache_folder = cache_folder
        self.batch_size = batch_size
        self.device = device
        self.local_files_only = local_files_only
        self._injected_model_factory = model_factory
        self._model: Any | None = None

    @property
    def metadata(self) -> RetrievalBackendMetadata:
        return RetrievalBackendMetadata(
            backend="sentence-transformers",
            backend_version="multilingual-e5-v1",
            model=MULTILINGUAL_E5_MODEL,
            model_version=MULTILINGUAL_E5_REVISION,
            dimensions=384,
            is_neural=True,
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "runtime": "sentence-transformers",
            "runtime_version": SENTENCE_TRANSFORMERS_VERSION,
            "transformers_version": TRANSFORMERS_VERSION,
            "torch_version": TORCH_VERSION,
            "query_prefix": "query: ",
            "passage_prefix": "passage: ",
            "normalization": "l2",
            "batch_size": self.batch_size,
            "device": self.device,
            "local_files_only": self.local_files_only,
            "trust_remote_code": False,
            "max_sequence_tokens": 512,
        }

    @property
    def runtime_status(self) -> dict[str, Any]:
        if self._injected_model_factory is not None:
            installed_versions = {
                "sentence-transformers": "test-double",
                "transformers": "test-double",
                "torch": "test-double",
            }
            ready = True
        else:
            installed_versions = {
                package: _installed_version(package)
                for package in ("sentence-transformers", "transformers", "torch")
            }
            ready = installed_versions == {
                "sentence-transformers": SENTENCE_TRANSFORMERS_VERSION,
                "transformers": TRANSFORMERS_VERSION,
                "torch": TORCH_VERSION,
            }
        return {
            "ready": ready,
            "dependencies": installed_versions,
            "required_versions": {
                "sentence-transformers": SENTENCE_TRANSFORMERS_VERSION,
                "transformers": TRANSFORMERS_VERSION,
                "torch": TORCH_VERSION,
            },
            "model_load": "lazy",
            "local_files_only": self.local_files_only,
        }

    def _model_factory(self) -> Callable[..., Any]:
        if self._injected_model_factory is not None:
            return self._injected_model_factory
        required_versions = {
            "sentence-transformers": SENTENCE_TRANSFORMERS_VERSION,
            "transformers": TRANSFORMERS_VERSION,
            "torch": TORCH_VERSION,
        }
        installed_versions = {
            package: _installed_version(package) for package in required_versions
        }
        if installed_versions != required_versions:
            found = ", ".join(
                f"{package}=={version}"
                for package, version in installed_versions.items()
            )
            required = ", ".join(
                f"{package}=={version}"
                for package, version in required_versions.items()
            )
            raise EmbeddingBackendUnavailableError(
                f"multilingual-e5-small requires {required}; found {found}. "
                'Run: python -m pip install -e ".[neural]"'
            )
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingBackendUnavailableError(
                "The neural retrieval backend is selected but its local "
                "runtime is not installed. Run: python -m pip install -e "
                '".[neural]"'
            ) from exc
        return SentenceTransformer

    def _load_model(self) -> Any:
        if self._model is None:
            self.cache_folder.mkdir(parents=True, exist_ok=True)
            factory = self._model_factory()
            try:
                self._model = factory(
                    MULTILINGUAL_E5_MODEL,
                    revision=MULTILINGUAL_E5_REVISION,
                    cache_folder=str(self.cache_folder),
                    device=self.device,
                    trust_remote_code=False,
                    local_files_only=self.local_files_only,
                )
            except Exception as exc:
                mode = (
                    "local cache only"
                    if self.local_files_only
                    else "local cache with download allowed"
                )
                raise EmbeddingBackendUnavailableError(
                    f"Could not load {MULTILINGUAL_E5_MODEL} at pinned "
                    f"revision {MULTILINGUAL_E5_REVISION} ({mode}): {exc}"
                ) from exc
        return self._model

    def _encode(self, texts: list[str], prefix: str) -> list[list[float]]:
        if not texts:
            return []
        prepared = [prefix + " ".join(text.split()) for text in texts]
        vectors = self._load_model().encode(
            prepared,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        raw_vectors = (
            vectors.tolist() if hasattr(vectors, "tolist") else vectors
        )
        return [[float(value) for value in vector] for vector in raw_vectors]

    def encode_query(self, text: str) -> list[float]:
        return self._encode([text], "query: ")[0]

    def encode_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, "passage: ")


def build_embedding_backend(
    backend_name: str,
    *,
    cache_folder: Path,
    batch_size: int = 32,
    device: str = "cpu",
    local_files_only: bool = False,
) -> HashingEmbeddingBackend | MultilingualE5SmallEmbeddingBackend:
    normalized_name = backend_name.strip().lower()
    if normalized_name == "hashing":
        return HashingEmbeddingBackend()
    if normalized_name in {"multilingual-e5-small", "e5-small"}:
        return MultilingualE5SmallEmbeddingBackend(
            cache_folder,
            batch_size=batch_size,
            device=device,
            local_files_only=local_files_only,
        )
    raise ValueError(
        "Unknown retrieval backend: "
        f"{backend_name}. Expected hashing or multilingual-e5-small."
    )

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import json
import urllib.error
import urllib.request


class EmbeddingError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenAIEmbeddingClient:
    api_key: str
    model: str
    dimensions: int | None = 1536
    base_url: str = "https://api.openai.com/v1"
    api_mode: str = "openai"
    max_workers: int = 8
    timeout_seconds: int = 60

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.api_mode == "ark_multimodal":
            workers = min(max(self.max_workers, 1), len(texts))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                return list(executor.map(self._embed_multimodal_text, texts))
        if self.api_mode != "openai":
            raise EmbeddingError(f"Unsupported embedding API mode: {self.api_mode}")

        payload: dict[str, object] = {
            "model": self.model,
            "input": texts,
        }
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingError(f"Embedding request failed with HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise EmbeddingError(f"Embedding request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(body)
            data = sorted(parsed["data"], key=lambda item: item["index"])
            embeddings = [item["embedding"] for item in data]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError("Embedding response did not match the expected format.") from exc

        if len(embeddings) != len(texts):
            raise EmbeddingError("Embedding response count did not match the input count.")
        return embeddings

    def _embed_multimodal_text(self, text: str) -> list[float]:
        payload: dict[str, object] = {
            "model": self.model,
            "input": [{"type": "text", "text": text}],
        }
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions

        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/embeddings/multimodal",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingError(f"Embedding request failed with HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise EmbeddingError(f"Embedding request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(body)
            embedding = parsed["data"]["embedding"]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError("Multimodal embedding response did not match the expected format.") from exc
        if not isinstance(embedding, list):
            raise EmbeddingError("Multimodal embedding response did not contain a vector.")
        return embedding

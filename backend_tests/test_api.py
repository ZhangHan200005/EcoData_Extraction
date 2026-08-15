from __future__ import annotations

import re
import unittest

from backend.api import app, health


class ApiConfigurationTests(unittest.TestCase):
    def test_cors_accepts_loopback_frontend_on_fallback_port(self) -> None:
        middleware = app.user_middleware[0]
        pattern = middleware.kwargs["allow_origin_regex"]

        self.assertIsNotNone(re.fullmatch(pattern, "http://localhost:3001"))
        self.assertIsNotNone(re.fullmatch(pattern, "http://127.0.0.1:3002"))
        self.assertIsNone(re.fullmatch(pattern, "https://example.com"))

    def test_health_exposes_active_retrieval_backend(self) -> None:
        payload = health()

        self.assertEqual("hashing", payload["retrieval_backend"]["backend"])
        self.assertEqual(
            "blake2b-character-ngram",
            payload["retrieval_backend"]["model"],
        )
        self.assertFalse(payload["retrieval_backend"]["is_neural"])
        self.assertTrue(payload["retrieval_backend_runtime"]["ready"])
        self.assertEqual(
            "python-standard-library",
            payload["retrieval_backend_runtime"]["dependency"],
        )
        self.assertTrue(payload["vector_cache"]["enabled"])
        self.assertEqual(
            "embedding-cache-key-v1",
            payload["vector_cache"]["key_version"],
        )
        self.assertEqual("pdfplumber", payload["parser_backend"])
        self.assertEqual(
            "pdfplumber-reading-order-v2", payload["parser_version"]
        )
        self.assertEqual(
            "parent-child-480char-v1", payload["chunking_version"]
        )


if __name__ == "__main__":
    unittest.main()

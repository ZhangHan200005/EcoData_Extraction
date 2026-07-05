import os
import unittest

from ecodata_extraction.config import load_openalex_api_key


class LoadOpenAlexApiKeyTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("OPENALEX_API_KEY", None)

    def test_loads_and_strips_api_key(self) -> None:
        os.environ["OPENALEX_API_KEY"] = "  test-key  "
        actual = load_openalex_api_key()
        self.assertEqual(actual, "test-key")

    def test_rejects_missing_api_key(self) -> None:
        os.environ.pop("OPENALEX_API_KEY", None)
        with self.assertRaises(ValueError):
            load_openalex_api_key()

    def test_rejects_blank_api_key(self) -> None:
        os.environ["OPENALEX_API_KEY"] = "  "
        with self.assertRaises(ValueError):
            load_openalex_api_key()


if __name__ == "__main__":
    unittest.main()
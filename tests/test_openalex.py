import unittest

from ecodata_extraction.openalex import build_search_params


class BuildSearchParamsTests(unittest.TestCase):
    def test_builds_clean_parameters(self) -> None:
        params = build_search_params(
            query="  nitrate agricultural runoff  ",
            api_key="  test-key  ",
            per_page=5,
        )

        self.assertEqual(
            params,
            {
                "search": "nitrate agricultural runoff",
                "per_page": 5,
                "api_key": "test-key",
            },
        )

    def test_rejects_blank_query_or_key(self) -> None:
        with self.assertRaises(ValueError):
            build_search_params("   ", "test-key")

        with self.assertRaises(ValueError):
            build_search_params("nitrate", "   ")

    def test_rejects_invalid_page_size(self) -> None:
        for per_page in (0, 101):
            with self.subTest(per_page=per_page):
                with self.assertRaises(ValueError):
                    build_search_params("nitrate", "test-key", per_page)


if __name__ == "__main__":
    unittest.main()

"""Helpers for searching OpenAlex."""

from typing import Dict, Union


SearchParam = Union[str, int]


def build_search_params(
    query: str,
    api_key: str,
    per_page: int = 10,
) -> Dict[str, SearchParam]:
    """Validate input and build parameters for an OpenAlex works search.

    Requirements:
    1. Remove whitespace around query and api_key.
    2. Reject an empty query or api_key with ValueError.
    3. Accept per_page only from 1 through 100.
    4. Return search, per_page, and api_key in a dictionary.
    """
    query = query.strip()
    api_key = api_key.strip()

    if query == "":
        raise ValueError("query is empty")

    if api_key == "":
        raise ValueError("api_key is empty")

    if per_page < 1 or per_page > 100:
        raise ValueError("per_page must be between 1 and 100")

    return {
        "search": query,
        "per_page": per_page,
        "api_key": api_key,
    }

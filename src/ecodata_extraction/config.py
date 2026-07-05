"""Read application configuration from environment variables."""

import os


def load_openalex_api_key() -> str:
    """Return a cleaned OpenAlex API key from the environment.

    Requirements:
    1. Read the ``OPENALEX_API_KEY`` environment variable.
    2. Remove whitespace around the value.
    3. Raise ``ValueError`` when the variable is missing or blank.
    4. Do not include the secret value in an error message.
    """
    api_key = os.getenv("OPENALEX_API_KEY")

    if api_key is None:
        raise ValueError("api key is missing")

    api_key = api_key.strip()

    if api_key == "":
        raise ValueError("api key is missing")

    return api_key
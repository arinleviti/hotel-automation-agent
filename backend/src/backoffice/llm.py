"""The one place that creates the Anthropic client (used by every node that calls Claude).

lru_cache = Python's built-in "remember the result": the client is created on the first call and
the same one is reused afterwards (it keeps its network connections open, so reusing it is faster).
Tests replace it with a fake by monkeypatching the module that uses it.
"""

from functools import lru_cache

import anthropic

from backoffice.config import get_settings


@lru_cache(maxsize=1)
def anthropic_client() -> anthropic.Anthropic:
    """The Anthropic SDK client. The key comes from .env through our settings (ANTHROPIC_API_KEY)."""
    key = get_settings().anthropic_api_key
    if key is None:
        raise RuntimeError("ANTHROPIC_API_KEY is missing: add it to the .env file at the repo root.")
    return anthropic.Anthropic(api_key=key.get_secret_value())

from unittest.mock import patch

import pytest

from minirun.providers.anthropic import AnthropicProvider
from minirun.providers.openai import OpenAIProvider
from minirun.runtime.harness import get_provider


class TestRuntimeHarness:
    def test_get_default_provider(self):
        with patch.dict("os.environ", {"LLM_PROVIDER": "openai"}):
            provider = get_provider()
            assert isinstance(provider, OpenAIProvider)

    def test_get_explicit_provider(self):
        provider = get_provider("anthropic")
        assert isinstance(provider, AnthropicProvider)

    def test_get_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("nonexistent")

    def test_get_default_fallback(self):
        with patch.dict("os.environ", clear=True):
            provider = get_provider()
            assert isinstance(provider, OpenAIProvider)

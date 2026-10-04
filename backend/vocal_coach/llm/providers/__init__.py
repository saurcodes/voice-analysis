"""Importing this package registers every built-in LLM provider.

Task 5 adds the anthropic provider module and imports it here alongside
openai_compatible so the side-effecting @register decorators run.
"""
from . import anthropic_provider  # noqa: F401
from . import openai_compatible  # noqa: F401


"""Three wires: OpenAI-compatible, Ollama native, Anthropic Messages.

Each exposes the same three members -- `chat`, `models`, `ready` -- so `providers.Router` never needs
to know which one it built.
"""
from .anthropic import Anthropic
from .ollama import Ollama
from .openai_compat import OpenAICompatible

__all__ = ["Anthropic", "Ollama", "OpenAICompatible"]

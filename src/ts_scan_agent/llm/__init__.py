import typing as t

from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Provider-agnostic interface for the one thing the pipeline ever asks an LLM to do:
    judge an ambiguous case and return structured, schema-shaped output. Mapping and
    Interview never call a provider SDK directly — only this interface — so swapping the
    backend (local Ollama, Anthropic, anything added later) never touches pipeline code."""

    @abstractmethod
    def judge(self, prompt: str, schema: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
        """Ask the model to reason about `prompt` and return a dict matching `schema`
        (a JSON Schema object). Implementations must enforce schema-shaped output, not just
        hope for it."""
        raise NotImplementedError


class NullLLMClient(LLMClient):
    """No-LLM fallback: every ambiguous case is reported as unresolved (never guesses) so
    Mapping degrades to 'ask the human in the Interview step' instead of failing outright.
    This is what makes the tool fully usable with zero API key / zero local model pulled."""

    def judge(self, prompt: str, schema: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
        return {}

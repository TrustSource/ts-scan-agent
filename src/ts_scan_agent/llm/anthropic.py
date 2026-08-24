import json
import typing as t
import warnings

from . import LLMClient

DEFAULT_MODEL = 'claude-opus-5'


class AnthropicLLMClient(LLMClient):
    """Optional cloud backend, behind the `ts-scan-agent[anthropic]` extra. Sends the
    judgment prompt (never the full repo) to the Anthropic API — only use this backend if
    that's acceptable for the repo being analyzed.

    judge() degrades to "unresolved" (empty dict) on any API error, same contract as
    OllamaLLMClient/NullLLMClient - callers throughout the pipeline already treat `{}` as
    "skip this enrichment, that's fine" (see mapping.py, ecosystem_proposals.py), so a
    transient API/auth/rate-limit failure on this optional cloud backend should never crash
    an otherwise-successful `analyze` run."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        try:
            import anthropic
        except ImportError as err:
            raise ImportError(
                'The Anthropic backend requires the "anthropic" extra: '
                'pip install "ts-scan-agent[anthropic]"'
            ) from err

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def judge(self, prompt: str, schema: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=2048,
                thinking={'type': 'adaptive'},
                output_config={
                    'effort': 'low',
                    'format': {'type': 'json_schema', 'schema': schema},
                },
                messages=[{'role': 'user', 'content': prompt}],
            )
        except self._anthropic.APIError as err:
            warnings.warn(f'Anthropic backend unavailable ({err}); deferring this item.')
            return {}

        # output_config.format guarantees the first text block is valid JSON matching schema.
        text = next((b.text for b in response.content if b.type == 'text'), None)
        if text is None:
            return {}
        return json.loads(text)

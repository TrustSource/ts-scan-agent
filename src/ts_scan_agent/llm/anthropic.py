import json
import typing as t

from . import LLMClient

DEFAULT_MODEL = 'claude-opus-4-7'


class AnthropicLLMClient(LLMClient):
    """Optional cloud backend, behind the `ts-scan-agent[anthropic]` extra. Sends the
    judgment prompt (never the full repo) to the Anthropic API — only use this backend if
    that's acceptable for the repo being analyzed."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        try:
            import anthropic
        except ImportError as err:
            raise ImportError(
                'The Anthropic backend requires the "anthropic" extra: '
                'pip install "ts-scan-agent[anthropic]"'
            ) from err

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def judge(self, prompt: str, schema: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            thinking={'type': 'adaptive'},
            output_config={'effort': 'low'},
            tools=[{
                'name': 'respond',
                'description': 'Return the judgment in the required schema.',
                'input_schema': schema,
            }],
            tool_choice={'type': 'tool', 'name': 'respond'},
            messages=[{'role': 'user', 'content': prompt}],
        )

        for block in response.content:
            if block.type == 'tool_use':
                return block.input

        return json.loads('{}')

import json
import typing as t
import warnings

import httpx

from . import LLMClient

DEFAULT_MODEL = 'qwen3:7b'
DEFAULT_BASE_URL = 'http://localhost:11434'


class OllamaLLMClient(LLMClient):
    """Default backend: a local Ollama server. Nothing about the repo being analyzed ever
    leaves the machine. Requires the model to be pulled beforehand (`ollama pull <model>`) —
    this client does not pull models itself.

    judge() degrades to "unresolved" (empty dict, same as NullLLMClient) rather than raising
    when the server is unreachable or the model isn't pulled - Ollama being the zero-setup
    default backend, a missing local server must never crash a whole `analyze` run; the
    affected cases just fall through to the interview step instead."""

    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL,
                 timeout: float = 60.0):
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def judge(self, prompt: str, schema: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
        try:
            response = httpx.post(
                f'{self.base_url}/api/chat',
                json={
                    'model': self.model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'format': schema,
                    'stream': False,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json()['message']['content']
            return json.loads(content)
        except (httpx.HTTPError, KeyError, ValueError) as err:
            warnings.warn(
                f'Ollama backend unavailable ({err}); deferring this item to the interview '
                f'instead. Is Ollama running with `{self.model}` pulled?'
            )
            return {}

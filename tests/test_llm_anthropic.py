import json
import types

import httpx
import pytest

anthropic = pytest.importorskip('anthropic')

from ts_scan_agent.llm.anthropic import AnthropicLLMClient, DEFAULT_MODEL

SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']}


def _client_with_fake_create(fake_create):
    client = AnthropicLLMClient(api_key='fake-key')
    client._client.messages.create = fake_create
    return client


def test_default_model_is_claude_opus_5():
    assert DEFAULT_MODEL == 'claude-opus-5'


def test_judge_parses_json_schema_text_block():
    text_block = types.SimpleNamespace(type='text', text=json.dumps({'ok': True}))

    def fake_create(**kwargs):
        assert kwargs['model'] == DEFAULT_MODEL
        assert kwargs['output_config']['format'] == {'type': 'json_schema', 'schema': SCHEMA}
        return types.SimpleNamespace(content=[text_block])

    client = _client_with_fake_create(fake_create)
    result = client.judge('classify this', SCHEMA)

    assert result == {'ok': True}


def test_judge_degrades_to_empty_dict_on_api_error():
    def fake_create(**kwargs):
        raise anthropic.APIConnectionError(request=httpx.Request('POST', 'https://api.anthropic.com'))

    client = _client_with_fake_create(fake_create)

    with pytest.warns(UserWarning):
        result = client.judge('classify this', SCHEMA)

    assert result == {}


def test_judge_returns_empty_dict_when_no_text_block_present():
    def fake_create(**kwargs):
        return types.SimpleNamespace(content=[])

    client = _client_with_fake_create(fake_create)
    result = client.judge('classify this', SCHEMA)

    assert result == {}

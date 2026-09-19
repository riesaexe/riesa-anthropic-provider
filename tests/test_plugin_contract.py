from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

from plugins.riesa_anthropic_provider.anthropic_adapter import ProviderRequestError
from plugins.riesa_anthropic_provider.plugin import AnthropicProviderPlugin


class _FakeMessages:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    async def create(self, **payload: Any) -> dict[str, Any]:
        self.payload = payload
        return {
            "id": "msg_fake",
            "model": payload["model"],
            "content": [{"type": "text", "text": "已完成联网查询"}],
            "usage": {"input_tokens": 2, "output_tokens": 3},
        }


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


class _FakeAnthropic:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


@pytest.mark.asyncio
async def test_provider_decorator_and_handler_use_host_provider_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = AnthropicProviderPlugin()
    plugin.set_plugin_config(
        {
            "plugin": {
                "config_version": "0.1.0",
                "enabled": True,
                "allow_web_search": True,
            }
        }
    )
    fake_client = _FakeClient()

    async def fake_get_client(provider: dict[str, Any]) -> _FakeClient:
        assert provider["api_key"] == "host-provider-key"
        assert provider["base_url"] == "https://third-party.example/anthropic"
        return fake_client

    monkeypatch.setattr(plugin, "_get_client", fake_get_client)
    request = {
        "api_provider": {
            "name": "shared-provider",
            "api_key": "host-provider-key",
            "base_url": "https://third-party.example/anthropic",
            "timeout": 120,
        },
        "context_items": [
            {"item_type": "UserMessageItem", "parts": [{"type": "text", "text": "搜索 MaiBot"}]}
        ],
        "model_info": {
            "model_identifier": "deepseek-v4-flash",
            "extra_params": {"web_search": {"enabled": True, "max_uses": 2}},
        },
        "max_tokens": 512,
        "tool_options": [],
        "temperature": None,
        "response_format": None,
    }

    result = await plugin.handle_provider(operation="response", request=request)

    assert result["item_schema_version"] == 1
    assert result["output_items"] == [
        {
            "item_type": "AssistantMessageItem",
            "parts": [{"type": "text", "text": "已完成联网查询"}],
        }
    ]
    assert fake_client.messages.payload is not None
    assert fake_client.messages.payload["tools"][-1]["max_uses"] == 2
    assert plugin.get_llm_providers()[0]["client_type"] == "anthropic_messages"


@pytest.mark.asyncio
async def test_provider_defaults_web_search_for_official_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = AnthropicProviderPlugin()
    plugin.set_plugin_config(
        {
            "plugin": {
                "config_version": "0.1.0",
                "enabled": True,
                "allow_web_search": True,
            }
        }
    )
    fake_client = _FakeClient()

    async def fake_get_client(provider: dict[str, Any]) -> _FakeClient:
        assert provider["base_url"] == "https://api.deepseek.com/anthropic"
        return fake_client

    monkeypatch.setattr(plugin, "_get_client", fake_get_client)
    await plugin.handle_provider(
        operation="response",
        request={
            "api_provider": {
                "api_key": "host-provider-key",
                "base_url": "https://api.deepseek.com/anthropic",
            },
            "context_items": [
                {"item_type": "UserMessageItem", "parts": [{"type": "text", "text": "搜索 MaiBot"}]}
            ],
            "model_info": {"model_identifier": "deepseek-v4-flash"},
            "max_tokens": 512,
            "tool_options": [],
            "response_format": None,
        },
    )

    assert fake_client.messages.payload is not None
    assert fake_client.messages.payload["tools"] == [
        {
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": 5,
        }
    ]


@pytest.mark.asyncio
async def test_provider_maps_explicit_host_auth_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_anthropic = ModuleType("anthropic")
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
    monkeypatch.setattr(fake_anthropic, "AsyncAnthropic", _FakeAnthropic, raising=False)
    plugin = AnthropicProviderPlugin()

    client = await plugin._get_client(
        {
            "api_key": "redacted",
            "base_url": "https://third-party.example/anthropic",
            "timeout": 60,
            "auth_type": "header",
            "auth_header_name": "Authorization",
            "auth_header_prefix": "Bearer",
        }
    )

    assert client.kwargs["default_headers"]["Authorization"] == "Bearer redacted"


@pytest.mark.asyncio
async def test_provider_rejects_unauthenticated_host_mode() -> None:
    plugin = AnthropicProviderPlugin()

    with pytest.raises(ProviderRequestError, match="auth_type=none"):
        await plugin._get_client(
            {
                "base_url": "https://third-party.example/anthropic",
                "auth_type": "none",
            }
        )


@pytest.mark.asyncio
async def test_provider_rejects_non_http_base_url() -> None:
    plugin = AnthropicProviderPlugin()

    with pytest.raises(ProviderRequestError, match="只支持 http:// 或 https://"):
        await plugin._get_client(
            {
                "api_key": "redacted",
                "base_url": "file:///tmp/anthropic",
            }
        )


@pytest.mark.asyncio
async def test_provider_rejects_credentials_in_base_url() -> None:
    plugin = AnthropicProviderPlugin()

    with pytest.raises(ProviderRequestError, match="不应包含 URL 用户名或密码"):
        await plugin._get_client(
            {
                "api_key": "redacted",
                "base_url": "https://user:password@third-party.example/anthropic",
            }
        )


@pytest.mark.asyncio
async def test_provider_normalizes_deepseek_root_url(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_anthropic = ModuleType("anthropic")
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
    monkeypatch.setattr(fake_anthropic, "AsyncAnthropic", _FakeAnthropic, raising=False)
    plugin = AnthropicProviderPlugin()

    client = await plugin._get_client(
        {
            "api_key": "redacted",
            "base_url": "https://api.deepseek.com",
            "timeout": 60,
        }
    )

    assert client.kwargs["base_url"] == "https://api.deepseek.com/anthropic"


@pytest.mark.asyncio
async def test_provider_rejects_deepseek_openai_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_anthropic = ModuleType("anthropic")
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
    monkeypatch.setattr(fake_anthropic, "AsyncAnthropic", _FakeAnthropic, raising=False)
    plugin = AnthropicProviderPlugin()

    with pytest.raises(ProviderRequestError, match="必须以 /anthropic 结尾"):
        await plugin._get_client(
            {
                "api_key": "redacted",
                "base_url": "https://api.deepseek.com/v1",
                "timeout": 60,
            }
        )

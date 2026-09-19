from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from maibot_sdk import LLMProvider, MaiBotPlugin

from .anthropic_adapter import CLIENT_TYPE, ProviderRequestError, build_anthropic_request, parse_anthropic_response
from .config_models import AnthropicProviderConfig, ProviderSettings


_DEEPSEEK_API_HOST = "api.deepseek.com"
_DEEPSEEK_ANTHROPIC_PATH = "/anthropic"


def _validate_base_url(base_url: str) -> None:
    try:
        parsed = urlsplit(base_url)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        username = parsed.username
        password = parsed.password
        _port = parsed.port
    except ValueError as exc:
        raise ProviderRequestError("api_provider.base_url 不是有效的 URL") from exc

    if scheme not in {"http", "https"}:
        raise ProviderRequestError(
            "api_provider.base_url 只支持 http:// 或 https://；"
            "请确认请求目标是可信的 Anthropic 兼容 endpoint"
        )
    if not hostname:
        raise ProviderRequestError("api_provider.base_url 必须包含有效的主机名")
    if username or password:
        raise ProviderRequestError(
            "api_provider.base_url 不应包含 URL 用户名或密码；"
            "请改用 Host Provider 的 api_key、请求头或查询参数配置鉴权"
        )


def _normalize_base_url(base_url: str) -> tuple[str, bool]:
    parsed = urlsplit(base_url)
    if parsed.hostname and parsed.hostname.lower() == _DEEPSEEK_API_HOST:
        path = parsed.path.rstrip("/")
        if not path:
            return (
                urlunsplit(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        _DEEPSEEK_ANTHROPIC_PATH,
                        parsed.query,
                        parsed.fragment,
                    )
                ),
                True,
            )
        if not path.endswith(_DEEPSEEK_ANTHROPIC_PATH):
            raise ProviderRequestError(
                "DeepSeek 官方 Anthropic Provider 的基础 URL 必须以 /anthropic 结尾；"
                "请使用 https://api.deepseek.com/anthropic，不要填写 OpenAI/Responses 的根路径或 /v1"
            )
        return (
            urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)),
            False,
        )
    return base_url, False


def _is_official_deepseek_provider(provider: Mapping[str, Any]) -> bool:
    parsed = urlsplit(str(provider.get("base_url") or "").strip())
    return bool(parsed.hostname and parsed.hostname.lower() == _DEEPSEEK_API_HOST)


class AnthropicProviderPlugin(MaiBotPlugin):
    config_model = AnthropicProviderConfig

    def __init__(self) -> None:
        super().__init__()
        self._clients: dict[tuple[Any, ...], Any] = {}

    async def on_load(self) -> None:
        self._get_logger().info("Anthropic 兼容模型 Provider 已加载；API 密钥复用 MaiBot 模型配置")

    async def on_unload(self) -> None:
        for client in self._clients.values():
            close = getattr(client, "close", None)
            if not callable(close):
                continue
            result = close()
            if inspect.isawaitable(result):
                await result
        self._clients.clear()

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        self.set_plugin_config(config_data)
        if scope == "self":
            await self.on_unload()

    @LLMProvider(
        CLIENT_TYPE,
        name="Anthropic Messages Provider",
        description="调用 Anthropic Messages 兼容接口，并可启用 DeepSeek 原生联网搜索。",
        version="0.1.3",
    )
    async def handle_provider(self, *, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        if operation != "response":
            raise ProviderRequestError(f"不支持的操作类型: {operation}")
        if not self._settings.enabled:
            raise ProviderRequestError("Anthropic Provider 已在插件配置中禁用")

        provider = request.get("api_provider")
        if not isinstance(provider, Mapping):
            raise ProviderRequestError("请求缺少 api_provider 配置快照")
        payload = build_anthropic_request(
            request,
            allow_web_search=self._settings.allow_web_search,
            default_web_search=_is_official_deepseek_provider(provider),
        )
        client = await self._get_client(provider)
        response = await client.messages.create(**payload)
        result = parse_anthropic_response(response)
        if self._settings.log_search_sources and result["search_sources"]:
            self._get_logger().info("Anthropic Provider 本轮返回 %d 个联网搜索来源", len(result["search_sources"]))
        return result

    @property
    def _settings(self) -> ProviderSettings:
        return cast(AnthropicProviderConfig, self.config).plugin

    async def _get_client(self, provider: Mapping[str, Any]) -> Any:
        auth_type = str(provider.get("auth_type") or "bearer").strip().lower()
        if auth_type == "none":
            raise ProviderRequestError(
                "Anthropic Provider 当前不支持 auth_type=none 的无鉴权 endpoint；"
                "请使用 bearer、header 或 query，并在 MaiBot Provider 中配置 API Key"
            )
        if auth_type not in {"bearer", "header", "query"}:
            raise ProviderRequestError(
                f"不支持的 api_provider.auth_type: {auth_type}；"
                "可选值为 bearer、header、query"
            )

        api_key = str(provider.get("api_key") or "").strip()
        base_url = str(provider.get("base_url") or "").strip()
        if not api_key:
            raise ProviderRequestError("api_provider.api_key 不能为空；请复用 MaiBot 已配置的 Provider 密钥")
        if not base_url:
            raise ProviderRequestError("api_provider.base_url 不能为空")
        _validate_base_url(base_url)
        base_url, was_corrected = _normalize_base_url(base_url)
        if was_corrected:
            self._get_logger().warning(
                "检测到 DeepSeek 官方根地址，Anthropic Provider 已自动改用 %s；"
                "建议直接在模型配置中填写该地址",
                base_url,
            )

        try:
            timeout = float(provider.get("timeout") or 120)
        except (TypeError, ValueError) as exc:
            raise ProviderRequestError("api_provider.timeout 必须是数字") from exc
        if timeout <= 0:
            raise ProviderRequestError("api_provider.timeout 必须是正数")
        headers = dict(provider.get("default_headers") or {})
        query = dict(provider.get("default_query") or {})
        if auth_type == "header":
            header_name = str(provider.get("auth_header_name") or "Authorization").strip()
            header_prefix = str(provider.get("auth_header_prefix") or "").strip()
            if header_name:
                headers.setdefault(header_name, f"{header_prefix} {api_key}".strip())
        elif auth_type == "query":
            query_name = str(provider.get("auth_query_name") or "api_key").strip()
            if query_name:
                query.setdefault(query_name, api_key)
        signature = (
            base_url,
            api_key,
            timeout,
            json.dumps(headers, sort_keys=True, ensure_ascii=False, default=str),
            json.dumps(query, sort_keys=True, ensure_ascii=False, default=str),
        )
        cached = self._clients.get(signature)
        if cached is not None:
            return cached

        if not _is_official_deepseek_provider({"base_url": base_url}):
            self._get_logger().warning(
                "Anthropic Provider 将按 Host 配置向非官方 endpoint 发送 API Key 和完整上下文；"
                "请确认该地址由可信管理员配置"
            )

        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise ProviderRequestError("缺少 anthropic 依赖，请先安装插件依赖") from exc

        client = AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
            default_headers=headers or None,
            default_query=query or None,
        )
        self._clients[signature] = client
        return client


def create_plugin() -> AnthropicProviderPlugin:
    return AnthropicProviderPlugin()

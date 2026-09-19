from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


CLIENT_TYPE = "anthropic_messages"
ITEM_SCHEMA_VERSION = 1
DEFAULT_WEB_SEARCH_TOOL = "web_search_20260209"
DEFAULT_WEB_SEARCH_MAX_USES = 5
DEFAULT_MAX_TOKENS = 4096
JSON_OBJECT_INSTRUCTION = (
    "Return exactly one valid JSON object. Do not wrap it in Markdown or add any text outside the JSON object."
)


class ProviderRequestError(ValueError):
    pass


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string(value: Any) -> str:
    return str(value or "").strip()


def _merge_extra_params(request: Mapping[str, Any]) -> dict[str, Any]:
    model_info = _mapping(request.get("model_info"))
    merged: dict[str, Any] = {}
    for source in (model_info.get("extra_params"), request.get("extra_params")):
        if not isinstance(source, Mapping):
            continue
        for key, value in source.items():
            if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
                merged[key] = {**_mapping(merged[key]), **value}
            else:
                merged[str(key)] = value
    return merged


def _is_search_tool(value: Any) -> bool:
    raw = _mapping(value)
    tool_type = _string(raw.get("type")).lower()
    name = _string(raw.get("name")).lower()
    return tool_type.startswith("web_search") or name == "web_search"


def _normalize_search_tool_type(value: Any) -> str:
    tool_type = _string(value)
    if tool_type.lower() == "web_search":
        return DEFAULT_WEB_SEARCH_TOOL
    return tool_type


def _search_settings(
    extra_params: Mapping[str, Any],
    *,
    default_enabled: bool = True,
) -> tuple[bool, str, int, bool]:
    enabled: bool | None = None
    explicitly_configured = False
    tool_type = DEFAULT_WEB_SEARCH_TOOL
    max_uses: Any = None

    for key in ("web_search", "search"):
        value = extra_params.get(key)
        if isinstance(value, bool):
            explicitly_configured = True
            enabled = value
        elif isinstance(value, Mapping):
            explicitly_configured = True
            enabled = bool(value.get("enabled", True))
            candidate_type = _string(value.get("tool_type") or value.get("type"))
            if candidate_type.lower().startswith("web_search"):
                tool_type = _normalize_search_tool_type(candidate_type)
            if value.get("max_uses") is not None:
                max_uses = value.get("max_uses")
        elif isinstance(value, str) and value:
            explicitly_configured = True
            enabled = value.lower().startswith("web_search")
            if enabled:
                tool_type = _normalize_search_tool_type(value)

    if "enable_web_search" in extra_params:
        explicitly_configured = True
        enabled = bool(extra_params.get("enable_web_search"))
    if extra_params.get("web_search_tool") is not None:
        candidate_type = _string(extra_params.get("web_search_tool"))
        if candidate_type.lower().startswith("web_search"):
            explicitly_configured = True
            enabled = True
            tool_type = _normalize_search_tool_type(candidate_type)
    if extra_params.get("web_search_max_uses") is not None:
        max_uses = extra_params.get("web_search_max_uses")

    for raw_tool in extra_params.get("tools", []):
        if _is_search_tool(raw_tool) and enabled is not False:
            explicitly_configured = True
            enabled = True
            raw_type = _string(_mapping(raw_tool).get("type"))
            if raw_type.lower().startswith("web_search"):
                tool_type = _normalize_search_tool_type(raw_type)
            if _mapping(raw_tool).get("max_uses") is not None:
                max_uses = _mapping(raw_tool).get("max_uses")

    normalized_max_uses = DEFAULT_WEB_SEARCH_MAX_USES if max_uses is None else max_uses
    try:
        normalized_max_uses = int(normalized_max_uses)
    except (TypeError, ValueError) as exc:
        raise ProviderRequestError("web_search.max_uses 必须是正整数") from exc
    if not 1 <= normalized_max_uses <= 50:
        raise ProviderRequestError("web_search.max_uses 必须在 1 到 50 之间")
    if not tool_type.lower().startswith("web_search"):
        tool_type = DEFAULT_WEB_SEARCH_TOOL
    return default_enabled if enabled is None else enabled, tool_type, normalized_max_uses, explicitly_configured


def _part_blocks(parts: Any, *, allow_images: bool) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if not isinstance(parts, Sequence) or isinstance(parts, (str, bytes, bytearray)):
        return blocks
    for raw_part in parts:
        part = _mapping(raw_part)
        part_type = _string(part.get("type")).lower()
        if part_type == "text":
            text = part.get("text")
            if isinstance(text, str) and text:
                blocks.append({"type": "text", "text": text})
            continue
        if part_type == "refusal":
            refusal = part.get("refusal")
            if isinstance(refusal, str) and refusal:
                blocks.append({"type": "text", "text": refusal})
            continue
        if part_type == "image" and allow_images:
            image_format = _string(part.get("image_format")).lower() or "png"
            media_type = image_format if image_format.startswith("image/") else f"image/{image_format}"
            image_base64 = part.get("image_base64")
            if isinstance(image_base64, str) and image_base64:
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    }
                )
    return blocks


def _append_message(messages: list[dict[str, Any]], role: str, content: Any) -> None:
    if not content:
        return
    new_content = content if isinstance(content, list) else [{"type": "text", "text": str(content)}]
    if messages and messages[-1]["role"] == role:
        previous = messages[-1]["content"]
        previous_list = previous if isinstance(previous, list) else [{"type": "text", "text": str(previous)}]
        messages[-1]["content"] = previous_list + new_content
        return
    messages.append({"role": role, "content": new_content})


def _context_to_messages(request: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    messages: list[dict[str, Any]] = []
    system_text: list[str] = []
    context_items = request.get("context_items", [])
    if not isinstance(context_items, Sequence) or isinstance(context_items, (str, bytes, bytearray)):
        raise ProviderRequestError("context_items 必须是列表")

    for raw_item in context_items:
        item = _mapping(raw_item)
        item_type = _string(item.get("item_type"))
        if item_type == "SystemMessageItem":
            system_text.extend(
                block["text"]
                for block in _part_blocks(item.get("parts"), allow_images=False)
                if block["type"] == "text"
            )
        elif item_type == "UserMessageItem":
            _append_message(messages, "user", _part_blocks(item.get("parts"), allow_images=True))
        elif item_type == "AssistantMessageItem":
            _append_message(messages, "assistant", _part_blocks(item.get("parts"), allow_images=False))
        elif item_type == "FunctionCallItem":
            tool_call = _mapping(item.get("tool_call"))
            call_id = _string(tool_call.get("call_id"))
            name = _string(tool_call.get("func_name"))
            if not call_id or not name:
                raise ProviderRequestError("FunctionCallItem 缺少 call_id 或 func_name")
            args = tool_call.get("args")
            _append_message(
                messages,
                "assistant",
                [{"type": "tool_use", "id": call_id, "name": name, "input": dict(_mapping(args))}],
            )
        elif item_type == "FunctionCallOutputItem":
            call_id = _string(item.get("call_id"))
            if not call_id:
                raise ProviderRequestError("FunctionCallOutputItem 缺少 call_id")
            output = item.get("output")
            _append_message(
                messages,
                "user",
                [{"type": "tool_result", "tool_use_id": call_id, "content": str(output or "")}],
            )
        elif item_type in {"ReasoningItem", "ProviderActivityItem", "ProviderOpaqueItem"}:
            continue
        elif item_type:
            raise ProviderRequestError(f"不支持的 Context Item 类型: {item_type}")

    if not messages:
        raise ProviderRequestError("请求没有可发送的 user/assistant 消息")
    return messages, system_text


def _function_tool(raw_tool: Any) -> dict[str, Any]:
    raw = _mapping(raw_tool)
    function = _mapping(raw.get("function"))
    if function:
        name = _string(function.get("name"))
        description = _string(function.get("description"))
        parameters = function.get("parameters")
    else:
        name = _string(raw.get("name"))
        description = _string(raw.get("description"))
        parameters = raw.get("input_schema") or raw.get("parameters")
    if not name:
        raise ProviderRequestError("函数工具缺少 name")
    schema = dict(_mapping(parameters)) or {"type": "object", "properties": {}}
    return {"name": name, "description": description, "input_schema": schema}


def _tool_choice(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    if _string(value.get("type")).lower() == "function":
        function = _mapping(value.get("function"))
        name = _string(function.get("name"))
        return {"type": "tool", "name": name} if name else "auto"
    return dict(value)


def _thinking_payload(extra_params: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    thinking = _mapping(extra_params.get("thinking"))
    if not thinking and isinstance(extra_params.get("thinking"), str):
        thinking = {"type": extra_params.get("thinking")}
    thinking_type = _string(thinking.get("type")).lower()
    if thinking_type not in {"enabled", "disabled"}:
        thinking_type = ""
    thinking_payload: dict[str, Any] | None = {"type": thinking_type} if thinking_type else None

    effort = _string(
        thinking.get("effort")
        or _mapping(extra_params.get("reasoning")).get("effort")
        or _mapping(extra_params.get("output_config")).get("effort")
    ).lower()
    output_config = {"effort": effort} if effort in {"low", "medium", "high", "max"} else None
    budget_tokens = thinking.get("budget_tokens")
    if thinking_payload and thinking_type == "enabled" and budget_tokens is not None:
        try:
            normalized_budget = int(budget_tokens)
        except (TypeError, ValueError) as exc:
            raise ProviderRequestError("thinking.budget_tokens 必须是正整数") from exc
        if normalized_budget <= 0:
            raise ProviderRequestError("thinking.budget_tokens 必须是正整数")
        thinking_payload["budget_tokens"] = normalized_budget
    return thinking_payload, output_config


def build_anthropic_request(
    request: Mapping[str, Any],
    *,
    allow_web_search: bool = True,
    default_web_search: bool = True,
) -> dict[str, Any]:
    model_info = _mapping(request.get("model_info"))
    model = _string(model_info.get("model_identifier") or model_info.get("name"))
    if not model:
        raise ProviderRequestError("model_info.model_identifier 不能为空")

    max_tokens = request.get("max_tokens") or model_info.get("max_tokens") or DEFAULT_MAX_TOKENS
    try:
        max_tokens = int(max_tokens)
    except (TypeError, ValueError) as exc:
        raise ProviderRequestError("max_tokens 必须是正整数") from exc
    if max_tokens <= 0:
        raise ProviderRequestError("max_tokens 必须是正整数")

    response_format = _mapping(request.get("response_format"))
    format_type = _string(response_format.get("format_type") or response_format.get("type")).lower()
    if format_type and format_type not in {"text", "none", "json_object"}:
        raise ProviderRequestError(
            "Anthropic Provider 当前支持 text 和 json_object response_format；json_schema 暂不支持"
        )

    messages, system_text = _context_to_messages(request)
    if format_type == "json_object":
        system_text.append(JSON_OBJECT_INSTRUCTION)
    extra_params = _merge_extra_params(request)
    search_enabled, search_type, search_max_uses, search_explicitly_configured = _search_settings(
        extra_params,
        default_enabled=default_web_search,
    )
    if search_enabled and not allow_web_search and search_explicitly_configured:
        raise ProviderRequestError("插件配置已禁止原生联网搜索")
    if not allow_web_search:
        search_enabled = False

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system_text:
        payload["system"] = "\n\n".join(system_text)

    temperature = request.get("temperature")
    if temperature is None and bool(model_info.get("send_temperature")):
        temperature = model_info.get("temperature")
    if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
        payload["temperature"] = temperature

    tool_payloads: list[dict[str, Any]] = []
    for raw_tool in request.get("tool_options", []) or []:
        tool_payloads.append(_function_tool(raw_tool))
    raw_extra_tools = extra_params.get("tools", [])
    if isinstance(raw_extra_tools, Sequence) and not isinstance(raw_extra_tools, (str, bytes, bytearray)):
        for raw_tool in raw_extra_tools:
            if _is_search_tool(raw_tool):
                continue
            tool_payloads.append(_function_tool(raw_tool))
    if search_enabled:
        tool_payloads.append(
            {
                "type": search_type,
                "name": "web_search",
                "max_uses": search_max_uses,
            }
        )
    if tool_payloads:
        payload["tools"] = tool_payloads

    if extra_params.get("tool_choice") is not None:
        payload["tool_choice"] = _tool_choice(extra_params.get("tool_choice"))
    thinking, output_config = _thinking_payload(extra_params)
    if thinking:
        payload["thinking"] = thinking
    if output_config:
        payload["output_config"] = output_config
    return payload


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _plain(model_dump(mode="json"))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    return value


def _collect_sources(value: Any, sources: list[dict[str, str]]) -> None:
    plain = _plain(value)
    if isinstance(plain, Mapping):
        value_type = _string(plain.get("type")).lower()
        if value_type in {"web_search_result", "citation"}:
            url = _string(plain.get("url") or plain.get("source_url"))
            title = _string(plain.get("title") or plain.get("source_title"))
            if url and not any(item.get("url") == url for item in sources):
                sources.append({"url": url, "title": title})
        for key in ("content", "results", "citations"):
            child = plain.get(key)
            if isinstance(child, Sequence) and not isinstance(child, (str, bytes, bytearray)):
                for item in child:
                    _collect_sources(item, sources)
        return
    if isinstance(plain, Sequence) and not isinstance(plain, (str, bytes, bytearray)):
        for item in plain:
            _collect_sources(item, sources)


def _usage(response: Any) -> dict[str, int] | None:
    raw_usage = _get(response, "usage")
    if raw_usage is None:
        return None
    prompt_tokens = int(_get(raw_usage, "input_tokens", 0) or 0)
    completion_tokens = int(_get(raw_usage, "output_tokens", 0) or 0)
    cache_hit = int(_get(raw_usage, "cache_read_input_tokens", 0) or 0)
    cache_miss = int(_get(raw_usage, "cache_creation_input_tokens", 0) or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "prompt_cache_hit_tokens": cache_hit,
        "prompt_cache_miss_tokens": cache_miss,
    }


def parse_anthropic_response(response: Any) -> dict[str, Any]:
    output_items: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []
    content = _get(response, "content", [])
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        for block in content:
            block_type = _string(_get(block, "type")).lower()
            if block_type == "text":
                text = _get(block, "text")
                if isinstance(text, str) and text:
                    output_items.append(
                        {
                            "item_type": "AssistantMessageItem",
                            "parts": [{"type": "text", "text": text}],
                        }
                    )
                _collect_sources(_get(block, "citations", []), sources)
            elif block_type == "thinking":
                thinking = _get(block, "thinking") or _get(block, "text")
                if isinstance(thinking, str) and thinking:
                    output_items.append(
                        {
                            "item_type": "ReasoningItem",
                            "representation": "raw_text",
                            "summary_parts": [],
                            "text_parts": [thinking],
                        }
                    )
            elif block_type == "tool_use":
                call_id = _string(_get(block, "id"))
                name = _string(_get(block, "name"))
                if call_id and name:
                    output_items.append(
                        {
                            "item_type": "FunctionCallItem",
                            "tool_call": {
                                "call_id": call_id,
                                "func_name": name,
                                "args": dict(_mapping(_plain(_get(block, "input", {})))),
                                "extra_content": {},
                            },
                        },
                    )
            elif block_type in {"server_tool_use", "web_search_tool_result"}:
                _collect_sources(block, sources)

    result: dict[str, Any] = {
        "item_schema_version": ITEM_SCHEMA_VERSION,
        "output_items": output_items,
        "usage": _usage(response),
        "response_id": _string(_get(response, "id")),
        "status": "completed",
        "search_sources": sources,
        "raw_data": {
            "id": _string(_get(response, "id")),
            "model": _string(_get(response, "model")),
            "stop_reason": _string(_get(response, "stop_reason")),
            "output_item_types": [item["item_type"] for item in output_items],
            "search_sources": sources,
        },
    }
    return result

from __future__ import annotations

import pytest

from anthropic_adapter import (
    ProviderRequestError,
    build_anthropic_request,
    parse_anthropic_response,
)


def _request(*, extra_params: dict | None = None, response_format: dict | None = None) -> dict:
    return {
        "context_items": [
            {
                "item_type": "SystemMessageItem",
                "parts": [{"type": "text", "text": "系统规则"}],
            },
            {
                "item_type": "UserMessageItem",
                "parts": [{"type": "text", "text": "请查最新资料"}],
            },
        ],
        "extra_params": extra_params or {},
        "max_tokens": 2048,
        "model_info": {
            "model_identifier": "deepseek-v4-flash",
            "extra_params": {},
            "send_temperature": True,
            "temperature": 0.2,
        },
        "response_format": response_format,
        "temperature": None,
        "tool_options": [],
    }


def test_build_request_reuses_model_extra_params_and_maps_context_tools() -> None:
    request = _request(
        extra_params={
            "web_search": {"enabled": True, "max_uses": 3},
            "reasoning": {"effort": "high"},
        }
    )
    request["model_info"]["extra_params"] = {
        "thinking": {"type": "enabled", "budget_tokens": 1024}
    }
    request["context_items"].extend(
        [
            {
                "item_type": "AssistantMessageItem",
                "parts": [{"type": "text", "text": "我来查一下"}],
            },
            {
                "item_type": "FunctionCallItem",
                "tool_call": {
                    "call_id": "call_1",
                    "func_name": "get_weather",
                    "args": {"city": "深圳"},
                },
            },
            {
                "item_type": "FunctionCallOutputItem",
                "call_id": "call_1",
                "output": "晴",
                "tool_name": "get_weather",
                "success": True,
            },
        ]
    )
    request["tool_options"] = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "查询天气",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }
    ]

    payload = build_anthropic_request(request)

    assert payload["model"] == "deepseek-v4-flash"
    assert payload["system"] == "系统规则"
    assert payload["temperature"] == 0.2
    assert payload["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    assert payload["output_config"] == {"effort": "high"}
    assert payload["tools"][0]["name"] == "get_weather"
    assert payload["tools"][-1] == {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": 3,
    }
    assert payload["messages"][1]["role"] == "assistant"
    assert payload["messages"][1]["content"][1]["type"] == "tool_use"
    assert payload["messages"][2]["content"][0]["type"] == "tool_result"


def test_responses_style_search_marker_is_converted_to_anthropic_tool() -> None:
    payload = build_anthropic_request(
        _request(extra_params={"tools": [{"type": "web_search"}]}),
    )

    assert payload["tools"] == [
        {
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": 5,
        }
    ]


def test_build_request_enables_web_search_by_default() -> None:
    payload = build_anthropic_request(_request())

    assert payload["tools"] == [
        {
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": 5,
        }
    ]


def test_json_object_response_format_uses_text_compatibility_mode() -> None:
    payload = build_anthropic_request(
        _request(response_format={"format_type": "json_object"}),
    )

    assert payload["system"] == (
        "系统规则\n\n"
        "Return exactly one valid JSON object. Do not wrap it in Markdown or add any text outside the JSON object."
    )
    assert "response_format" not in payload


def test_build_request_allows_explicit_search_disable() -> None:
    payload = build_anthropic_request(_request(extra_params={"web_search": {"enabled": False}}))

    assert "tools" not in payload


def test_build_request_keeps_third_party_search_opt_in() -> None:
    payload = build_anthropic_request(_request(), default_web_search=False)

    assert "tools" not in payload


def test_global_search_disable_suppresses_default_without_error() -> None:
    payload = build_anthropic_request(_request(), allow_web_search=False)

    assert "tools" not in payload


def test_parse_response_keeps_text_reasoning_tools_usage_and_sources() -> None:
    response = {
        "id": "msg_1",
        "model": "deepseek-v4-flash",
        "stop_reason": "end_turn",
        "content": [
            {"type": "thinking", "thinking": "先核验"},
            {
                "type": "text",
                "text": "结论",
                "citations": [{"type": "web_search_result", "url": "https://example.com", "title": "来源"}],
            },
            {
                "type": "web_search_tool_result",
                "content": [{"type": "web_search_result", "url": "https://example.com/2", "title": "第二来源"}],
            },
            {"type": "tool_use", "id": "tool_1", "name": "lookup", "input": {"q": "x"}},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 4},
    }

    result = parse_anthropic_response(response)

    assert result["item_schema_version"] == 1
    assert [item["item_type"] for item in result["output_items"]] == [
        "ReasoningItem",
        "AssistantMessageItem",
        "FunctionCallItem",
    ]
    assert result["output_items"][0]["text_parts"] == ["先核验"]
    assert result["output_items"][1]["parts"] == [{"type": "text", "text": "结论"}]
    assert result["output_items"][2]["tool_call"]["func_name"] == "lookup"
    assert "content" not in result
    assert "reasoning_content" not in result
    assert "tool_calls" not in result
    assert result["usage"]["total_tokens"] == 14
    assert [source["url"] for source in result["search_sources"]] == [
        "https://example.com",
        "https://example.com/2",
    ]


def test_unsupported_response_format_and_disabled_search_fail_loudly() -> None:
    with pytest.raises(ProviderRequestError, match="response_format"):
        build_anthropic_request(_request(response_format={"format_type": "json_schema"}))

    with pytest.raises(ProviderRequestError, match="禁止"):
        build_anthropic_request(
            _request(extra_params={"web_search": True}),
            allow_web_search=False,
        )

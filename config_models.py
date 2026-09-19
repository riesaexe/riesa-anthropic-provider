from __future__ import annotations

from maibot_sdk import Field, PluginConfigBase


class ProviderSettings(PluginConfigBase):
    __ui_label__ = "Anthropic Provider 设置"
    __ui_icon__ = "globe"

    config_version: str = Field(
        default="0.1.0",
        description="插件配置版本",
        json_schema_extra={"label": {"zh_CN": "配置版本"}},
    )
    enabled: bool = Field(
        default=True,
        description="是否启用 Provider 请求",
        json_schema_extra={
            "x-widget": "switch",
            "label": {"zh_CN": "启用 Provider"},
        },
    )
    allow_web_search: bool = Field(
        default=True,
        description="是否允许模型启用原生联网搜索",
        json_schema_extra={
            "x-widget": "switch",
            "label": {"zh_CN": "允许联网搜索"},
        },
    )
    log_search_sources: bool = Field(
        default=False,
        description="是否在插件日志记录搜索来源数量",
        json_schema_extra={
            "x-widget": "switch",
            "label": {"zh_CN": "记录搜索来源"},
        },
    )


class AnthropicProviderConfig(PluginConfigBase):
    plugin: ProviderSettings = Field(default_factory=ProviderSettings)

# Anthropic 兼容模型 Provider

这是一个 MaiBot LLM Provider 插件。它注册标准的 `anthropic_messages` 客户端类型，把 MaiBot 的统一 `ResponseRequest` 转换为 Anthropic Messages 请求，适用于 DeepSeek Anthropic API 以及遵循相同协议的第三方服务。

插件默认复用 MaiBot Host 已经传入的 Provider 配置和 API Key，不在插件配置中另存一份密钥。配置完成后，模型可以直接被 `replyer`、`utils`、`planner` 等 MaiBot 任务使用，不需要额外的 Tool 调用。

## 为什么开发这个插件

MaiBot 当前的内置模型接入主要使用 Responses 等 Host 支持的客户端格式，而 DeepSeek 的 Responses 接口与 Anthropic 接口并不具备完全相同的工具能力。对于需要联网检索的场景，DeepSeek Anthropic API 提供了原生 `web_search` 工具，因此需要一个协议适配层，把 MaiBot 的统一请求转换为 Anthropic Messages 请求。

这个插件解决的是模型客户端协议接入问题，不是另一个独立的搜索机器人，也不需要在 MaiBot 中额外创建 Tool 调用链。

## 它解决了什么问题

- 在 MaiBot 中增加标准的 `anthropic_messages` LLM Provider。
- 让官方 DeepSeek Anthropic API 可以使用原生联网搜索。
- 让兼容 Anthropic Messages 协议的第三方服务也能使用同一套 Provider 接入方式。
- 复用 MaiBot Host 传入的 `api_provider` 快照和 API Key，避免插件维护第二套密钥配置。
- 把 Anthropic 响应转换为 MaiBot 当前的 Item schema，返回文本、思考、工具调用和搜索来源。
- 对官方 DeepSeek 地址默认启用联网搜索；第三方地址默认不主动注入搜索工具，避免兼容性问题。

## 与同类型方案的区别

| 方案 | 接入位置 | API Key 配置 | 第三方 Anthropic 服务 | 联网搜索行为 |
| --- | --- | --- | --- | --- |
| MaiBot 原生 Responses Provider | MaiBot Host 内置客户端 | 使用 Host 配置 | 取决于 Host 客户端兼容性 | 使用 Responses 的工具能力 |
| [deepseek-anthropic-provider](https://github.com/LowValueTarget777/deepseek-anthropic-provider) | 社区插件 | 插件内部单独填写 | 主要面向 DeepSeek 官方 API | 由该插件自己的配置和调用流程控制 |
| 本插件 | MaiBot LLM Provider 扩展点 | 复用 Host 的 Provider 快照 | 支持，地址由 Host Provider 配置决定 | 官方 DeepSeek 默认开启，第三方默认关闭，可手动覆盖 |

本插件的核心区别是：它注册的是 MaiBot 的 LLM Provider，而不是额外的聊天指令或搜索 Tool。选择 `anthropic_messages (riesa.anthropic-provider)` 后，该模型可以像其他 MaiBot 模型一样被 `replyer`、`utils` 等任务使用；API Key、超时、额外请求头和查询参数仍由 MaiBot 的模型 Provider 配置管理。

需要注意的是，MaiBot 当前的 `APIProvider` 没有“引用另一个 Provider”的字段。因此仍要在 `model_config.toml` 中新增一个 Anthropic Provider 条目，并把同一个密钥填入该条目；这是模型配置层的并列条目，不是插件自己的密钥。之后模型仍可放入已有的 `replyer`、`utils` 等任务列表。

> **重要：基础 URL 必须对应 Anthropic 格式。** 选择 `anthropic_messages (riesa.anthropic-provider)` 时，DeepSeek 官方 API 请填写 `https://api.deepseek.com/anthropic`。`https://api.deepseek.com` 是 OpenAI/Responses 格式的根地址，不能直接作为 Anthropic Provider 的地址。插件遇到官方根地址时会自动补上 `/anthropic`，但建议从配置开始就填写完整地址；如果填写了官方的 `/v1` 等非 Anthropic 路径，插件会直接报出修正提示。第三方服务则请填写该服务文档提供的 Anthropic 兼容入口，插件不会擅自给第三方地址追加路径。

> **安全边界：`base_url` 是高权限配置。** 任何能够修改 MaiBot Host Provider 配置的人，都可以决定 API Key 和完整上下文发送到哪里。插件只接受 `http://` 或 `https://`，但为了保留本地部署和第三方兼容 endpoint 的灵活性，不会把 `localhost`、局域网地址或云元数据地址自动当成安全地址拦截。请只使用自己信任的服务地址；远程服务优先使用 HTTPS，并确认该服务会如何处理 API Key、上下文和搜索内容。插件不提供 SSRF 隔离能力。

## 安装

正常安装插件本身即可，不需要修改 MaiBot 主程序，也不需要重新安装或修改 `maibot-dashboard`。插件管理器会按清单安装依赖；MaiBot Runner 会根据 `config_models.py` 自动生成插件配置，通常不需要手动复制 `config.example.toml`。

如果手动安装，可以把本仓库目录放到：

```text
Maibot/plugins/riesa_anthropic_provider/
```

然后重启 MaiBot 或重新加载插件。开发者在本地运行测试时才需要进入插件目录执行 `uv sync`；普通用户不需要为此修改主框架。

插件配置默认值如下：

- `启用 Provider`：开启。
- `允许联网搜索`：开启。
- `记录搜索来源`：关闭。

这些配置会在插件设置页中以中文显示。配置文件中的字段名仍保持稳定的英文键名，以便 MaiBot 配置系统和后续版本使用。

## 模型配置

不要把真实密钥写入本 README。下面的 `<沿用现有密钥>` 只是占位符；实际使用时填入你已经在 MaiBot 中管理的同一密钥。

```toml
[[api_providers]]
name = "DeepSeek-anthropic"
base_url = "https://api.deepseek.com/anthropic"
api_key = "<沿用现有密钥>"
client_type = "anthropic_messages"
timeout = 300

[[models]]
model_identifier = "<Anthropic 接口实际模型名>"
name = "deepseek-anthropic-search"
api_provider = "DeepSeek-anthropic"
send_temperature = true
force_stream_mode = false

# 默认会自动启用 web_search；以下参数用于覆盖工具版本和次数
[models.extra_params.web_search]
tool_type = "web_search_20260209"
max_uses = 5

[models.extra_params.thinking]
type = "enabled"
budget_tokens = 4096

[models.extra_params.reasoning]
effort = "high"

[model_task_config.replyer]
model_list = ["deepseek-anthropic-search"]

[model_task_config.utils]
model_list = ["deepseek-anthropic-search"]
```

实际使用的模型名称、搜索工具版本和思考参数应以服务商当前文档为准。旧版工具可以把 `tool_type` 改成服务商支持的 `web_search_*` 值。也可以使用 MaiBot 现有 Responses 风格的模型参数：`extra_params.tools = [{ type = "web_search" }]`，插件会把它转换成 Anthropic 原生搜索工具。

如果第三方服务需要额外请求头或查询参数，继续使用 MaiBot 的 Provider 配置：

```toml
[api_providers.default_headers]
X-Provider-Project = "<项目标识>"

[api_providers.default_query]
tenant = "<租户标识>"
```

Anthropic SDK 会使用 `api_key` 发送 Anthropic 约定的认证头。`auth_type = "header"` 时，插件会按 `auth_header_name` 和 `auth_header_prefix` 自动把同一个 `api_key` 转成请求头；`auth_type = "query"` 时会按 `auth_query_name` 放入查询参数。第三方若有额外鉴权字段，再补充 `default_headers` 或 `default_query`。

MaiBot 允许 Provider 使用 `auth_type = "none"` 表示无鉴权端点，但本插件当前要求 Anthropic 兼容服务使用 API Key，因此会明确拒绝 `auth_type = "none"`，不会把空密钥请求发送出去。请使用 `bearer`、`header` 或 `query` 并配置 API Key。

## 搜索行为

- 使用官方 DeepSeek 地址正常添加 `anthropic_messages` 模型时，插件默认会把原生 `web_search` 工具加入请求，不需要在 WebUI 中额外开启联网搜索开关。第三方 Anthropic 服务默认不注入该工具，确认兼容后可在模型额外参数中显式开启。
- Anthropic Provider 在模型编辑页不一定显示 MaiBot Responses Provider 的“启用联网搜索”开关，这是正常的；插件会按 Provider 地址自行决定默认策略。
- `web_search.enabled = true` 只代表把原生搜索工具暴露给模型，是否实际搜索仍由模型决定。
- `max_uses` 默认是 5，允许范围是 1 到 50。
- 如果某个模型不希望联网搜索，在该模型的额外参数中设置 `web_search.enabled = false`；插件会按模型级配置关闭默认工具。
- 插件配置中的 `allow_web_search = false` 会关闭默认搜索；如果模型额外参数明确请求搜索，插件会报错，不会静默放行。
- 搜索来源会保留在 Provider 返回值的 `search_sources` 和 `raw_data.search_sources` 中，供 MaiBot 的响应诊断链路使用；当前版本不会强行把来源 URL 拼到聊天正文末尾。

## 当前边界

- 当前版本实现非流式 `response` 主链路；Host 侧传入自定义流式处理器或响应解析器时，MaiBot 会拒绝该 Provider 请求。模型、思考和联网搜索全部结束后才会返回完整结果，因此不会先显示首个 token，体感速度取决于完整生成和搜索耗时。
- MaiBot 当前上下文会作为一次完整请求发送给 DeepSeek，输入 Token 成本和隐私暴露面可能高于 Host 原生流式或上下文优化链路。这是当前 PluginLLMClient 扩展点的限制，不是额外搜索 Tool 的问题。
- 如果其他插件在 MaiBot 完成全部插件激活前就在 `on_load` 中立即调用模型，第一次请求可能暂时看到 `anthropic_messages 类型的 Client 未注册`。这是 Host 的插件激活顺序竞态；Provider 完成注册后的正常请求不受影响。
- 当前版本只实现对话响应，不实现 embedding 和 audio transcription。
- `text` 正常支持；`json_object` 会转为文本提示，要求模型只返回一个 JSON 对象；`json_schema` 暂不支持，使用时会明确报错。
- 图片输入会转换为 Anthropic base64 图片块；是否可用取决于实际模型和服务商。
- 搜索工具的版本名称可能随服务商文档更新；如果服务商要求其他带日期的 `web_search_*` 类型，可在模型额外参数中覆盖。
- 插件不修改 `Maibot/src/`、`model_config.toml` 或现有社区 Tool 插件。

## 安全与配置边界

插件不会修改 MaiBot 主程序。它只接收 Host 在调用时传入的 Provider 配置快照，并在进程内缓存对应的 Anthropic 客户端。插件配置文件只控制 Provider 是否启用、联网搜索策略和搜索来源日志，不保存 API Key。

运行时会拒绝没有 `http/https` scheme、没有主机名或包含 URL 用户名/密码的 `base_url`。除此之外，插件不会判断地址是否为公网、内网、`localhost` 或云元数据地址，因为这些地址可能是用户明确配置的本地代理或第三方兼容服务。请把 Provider 配置权限视为敏感权限：请求会携带 Host Provider 中的 API Key，以及 MaiBot 发给模型的完整上下文；非官方 endpoint 的可信性和数据处理责任由部署者确认。

不要把 `config.toml`、API Key、完整运行日志或包含上下文的请求体提交到 GitHub。

## 开发与验证

在插件目录执行：

```bash
uv run --no-project pytest -q
uv run --no-project --with ruff ruff check anthropic_adapter.py config_models.py plugin.py tests
```

当前发布版包含针对请求转换、搜索默认策略、URL 防呆、`response_format` 兼容性、搜索来源提取和 MaiBot Item schema 的测试。

## 官方协议参考

- [DeepSeek Anthropic API](https://api-docs.deepseek.com/guides/anthropic_api/)
- [DeepSeek Responses API](https://api-docs.deepseek.com/guides/responses_api/)
- [MaiBot LLM Provider 文档](https://docs.mai-mai.org/develop/llm-providers)
- [MaiBot 插件发布说明](https://docs.mai-mai.org/plugin/submission)
- [项目仓库](https://github.com/riesaexe/riesa-anthropic-provider)
- [问题反馈](https://github.com/riesaexe/riesa-anthropic-provider/issues)

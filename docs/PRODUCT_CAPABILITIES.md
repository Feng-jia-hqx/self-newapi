# New API 产品能力全景梳理

> **项目定位**：新一代大模型网关与 AI 资产管理系统（基于 One API 演进）
> **目标读者**：产品/架构/集成方工程师
> **生成时间**：2026-07-25
> **梳理范围**：new-api 当前主干（本地路径 /Users/fengjia/new-api）

---

## 目录

1. [产品定位与核心价值](#1-产品定位与核心价值)
2. [整体架构与目录](#2-整体架构与目录)
3. [AI 上游适配能力](#3-ai-上游适配能力)（50+ 提供商）
4. [用户与权限体系](#4-用户与权限体系)
5. [认证与登录方式](#5-认证与登录方式)
6. [渠道与路由分发](#6-渠道与路由分发)
7. [计费表达式与配额系统](#7-计费表达式与配额系统)
8. [充值与支付订阅](#8-充值与支付订阅)
9. [后台管理与运营](#9-后台管理与运营)
10. [可观测、日志与审计](#10-可观测日志与审计)
11. [安全与速率限制](#11-安全与速率限制)
12. [前端能力](#12-前端能力)
13. [辅助能力](#13-辅助能力oauth邮件passkey文件缓存)
14. [运维与部署](#14-运维与部署)
15. [API 接口概览](#15-api-接口概览)

---

## 1. 产品定位与核心价值

### 1.1 一句话定位

**New API 是一个统一的 AI 模型接入网关 + 多租户 AI 资产/计费/运营管理平台**。

它解决的核心痛点：

| 痛点 | New API 的方案 |
|------|----------------|
| 多个 AI 厂商 API 格式不统一 | 统一对外暴露 OpenAI / Anthropic / Gemini 兼容格式，内置 40+ 上游适配 |
| 团队内部分配调用额度困难 | 多用户/分组/订阅/TopUp 模型，按次按量精确计费 |
| 不同上游的 Key / 账号分散管理 | "渠道（Channel）" 抽象 + 分组权重 + 自动重试 |
| 上游价格波动、模型上下架 | 模型元数据 + 同步机制 |
| 内部使用合规审计 | 完整的请求日志 + 消耗日志 + Uptime Kuma 探针 + Turnstile |
| 私有化部署 / 数据不出域 | 单二进制 + 三库兼容（SQLite/MySQL/PostgreSQL）+ Docker |

### 1.2 适用场景

- **企业内部 AI 平台**：统一接入多种大模型，给员工分配配额
- **SaaS 型 AI 代理/分发**：二次销售 AI 能力，按用量计费
- **AI 应用网关**：在应用与上游之间做格式转换、限流、降级、重试
- **研发自托管**：私有化部署，离线/内网使用

### 1.3 核心功能（来自 README）

- 🎨 UI（React 18 + Vite + Semi Design，@douyinfe/semi-ui）
- 🌍 多语言（zh-CN / zh-TW / en / fr / ja / vi / ru）
- 🔄 数据兼容（完全兼容原版 One API 数据库）
- 📈 数据看板（可视化控制台与统计分析）
- 🔒 权限管理（令牌分组、模型限制、用户管理）

---

## 2. 整体架构与目录

### 2.1 分层架构

```
HTTP 请求
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│  Router  (Gin)                                               │
│  ├─ api-router      后台 / 用户管理 / OAuth / 充值 / 日志    │
│  ├─ relay-router    /v1/chat/completions 等 AI 代理         │
│  ├─ video-router    /v1/video/* 异步视频任务                │
│  ├─ dashboard       /api/dashboard/*                         │
│  └─ web-router      静态 SPA                                 │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│  Middleware                                                  │
│  鉴权 / 速率限制 / 分布式 / 审计 / 缓存 / CORS / 压缩        │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│  Controller → Service → Model (GORM)                        │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│  Relay 层（relay/）                                          │
│  ├─ relay/           chat/embedding/image/audio 主入口      │
│  ├─ relay/channel/   40+ 厂商适配器                          │
│  ├─ relay/common/    通用 helpers                            │
│  ├─ relay/helper/    校验、计费、token 统计                  │
│  └─ relay/handler    各协议 handler（OpenAI/Anthropic/...） │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│  Setting 层（运行时配置）                                    │
│  system / operation / ratio / model / billing / perf / ...  │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│  存储：SQLite | MySQL | PostgreSQL  +  Redis（可选）          │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 顶层目录

| 目录 | 职责 |
|------|------|
| `router/` | HTTP 路由（API、Relay、Dashboard、Web） |
| `controller/` | HTTP 处理函数 |
| `service/` | 业务逻辑（auth、billing、channel、task、topup、subscription...） |
| `model/` | GORM 数据模型 |
| `relay/` | AI 代理核心 |
| `relay/channel/` | 40+ 上游适配器 |
| `middleware/` | Gin 中间件 |
| `setting/` | 运行时配置（ratio/model/operation/system/performance/billing） |
| `dto/` | 请求/响应 DTO |
| `constant/` | 常量（API/Channel/Context Key） |
| `types/` | 类型定义（relay format、file source、error） |
| `common/` | 工具（JSON/Redis/Env/rate-limit/...） |
| `i18n/` | 后端国际化（go-i18n，en/zh） |
| `oauth/` | OAuth 提供商（GitHub/Discord/LinuxDO/WeChat/Telegram/OIDC） |
| `pkg/` | 内部包（cachex、ionet） |
| `web/` | 前端（React 18 + Vite + Semi Design；Tailwind 作为辅助样式工具存在） |
| `docs/` | 文档与 OpenAPI 定义 |
| `electron/` | 桌面端（桌面客户端） |

---

## 3. AI 上游适配能力

### 3.1 支持的上游提供商（50+）

每个 provider 在 `relay/channel/<name>/` 下都有一个 adaptor 实现，并通过 `constant.APIType*` 暴露注册。

#### 3.1.1 适配器实现形态分类

| 形态 | 说明 | 典型 provider |
|------|------|---------------|
| **Native** | 自定义 `ConvertOpenAIRequest` 把 OpenAI 请求翻译成上游私有格式 | Claude / Gemini / Baidu / Cohere / Zhipu / Xunfei / Tencent / PaLM / Cloudflare / Coze / Dify / AWS / Vertex / Ali / Jimeng / Minimax / Volcengine / Moonshot / DeepSeek / xAI / MokaAI / Perplexity / SiliconFlow |
| **Pass-through（OpenAI 兼容）** | `ConvertOpenAIRequest` 原样返回，上游协议本就是 OpenAI 兼容 | Ollama / Mistral / Submodel / Replicate / Codex |
| **Generic proxy** | 没有自己的 adaptor，直接 `openai.Adaptor{}` 兜底 | AI360 / LingYiWanWu / OpenRouter / Xinference |
| **Task adaptor（异步）** | 在 `relay/channel/task/` 实现 `TaskAdaptor`（submit + poll） | Suno / Sora / Ali-wan / Kling / Jimeng / Vertex-Veo / Vidu / Doubao / Gemini-Veo / Hailuo |

#### 3.1.2 完整能力矩阵

> **Y** = 自定义实现；**P** = OpenAI 兼容直通；**N** = 占位/未实现；**T** = 走 `relay/channel/task/`。

| Provider | Channel Type | API Type | Chat | Image | Audio | Video | Embedding | Rerank | Task | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|
| **openai** | `ChannelTypeOpenAI` | `APITypeOpenAI` | Y | Y | Y | T(sora) | Y | P | Sora video | 原生：Realtime WS、Responses API、Image edits、Whisper+TTS、流式、Tool Calls、Vision、Moderation、DALL-E/gpt-image |
| **claude** | `ChannelTypeAnthropic` | `APITypeAnthropic` | Y | N | N | – | N | N | – | Anthropic Messages 原生；Extended Thinking、tool use、vision、message delta usage |
| **gemini** | `ChannelTypeGemini` | `APITypeGemini` | Y | Y | N | T(gemini) | Y | N | Veo video | Gemini generateContent 原生；Imagen、batchEmbedContents、Responses API 翻译、思考适配、SSE |
| **vertex** | `ChannelTypeVertexAi` | `APITypeVertexAi` | Y | N | N | T(vertex) | P | N | Veo video | Google Cloud Vertex AI；服务账号 JWT、区域 endpoint、OAI→Gemini 翻译 |
| **ali** | `ChannelTypeAli` | `APITypeAli` | Y | Y | N | T(ali) | P | Y | Wan video | DashScope；多格式（OAI/Claude/native Ali）；同步+异步图像（wan2.6、z-image、qwen-image）；image edits、rerank、SSE |
| **baidu** | `ChannelTypeBaidu` | `APITypeBaidu` | Y | Y | N | – | P | P | – | 百度千帆 v1；access-token OAuth |
| **baidu_v2** | `ChannelTypeBaiduV2` | `APITypeBaiduV2` | Y | Y | N | – | P | Y | – | 千帆 v2；含 Claude/Responses 转换 stub |
| **zhipu** | `ChannelTypeZhipu` | `APITypeZhipu` | Y | N | N | – | P | N | – | 智谱 GLM；OAI→Zhipu 流式 |
| **zhipu_4v** | `ChannelTypeZhipu_v4` | `APITypeZhipuV4` | Y | Y | N | – | P | N | – | 智谱 GLM-4V；`/api/paas/v4/images/generations`；编程套餐专用 base |
| **xunfei** | `ChannelTypeXunfei` | `APITypeXunfei` | Y | N | N | – | P | N | – | 讯飞星火；自定义协议 + 自定义流式 |
| **tencent** | `ChannelTypeTencent` | `APITypeTencent` | Y | N | N | – | P | N | – | 腾讯混元；自定义格式 + 签名鉴权 |
| **palm** | `ChannelTypePaLM` | `APITypePaLM` | Y | N | N | – | P | N | – | Google PaLM（legacy） |
| **aws** | `ChannelTypeAws` | `APITypeAws` | Y | N | N | – | P | N | – | AWS Bedrock；Claude 模型；IAM 签名 |
| **cohere** | `ChannelTypeCohere` | `APITypeCohere` | Y | N | N | – | N | Y | – | Cohere；自定义 chat + 原生 `/v1/rerank` + 自定义流式 |
| **jina** | `ChannelTypeJina` | `APITypeJina` | P | N | N | – | Y | Y | – | Jina AI；Embedding + Rerank；chat 透传；剥离 `encodingFormat` |
| **cloudflare** | `ChannelCloudflare` | `APITypeCloudflare` | Y | N | N | – | P | N | – | Cloudflare Workers AI；AI Gateway 集成 |
| **minimax** | `ChannelTypeMiniMax` | `APITypeMiniMax` | Y | Y | Y | T(hailuo) | P | N | Hailuo video | MiniMax；OAI 兼容 chat、自定义图像、MiniMax TTS、Claude 兼容委托 |
| **volcengine** | `ChannelTypeVolcEngine` | `APITypeVolcEngine` | Y | Y | Y | T(doubao) | P | N | Doubao video | 字节火山 Ark；OAI 兼容 chat + bot endpoint；图像 `/api/v3/images/generations`；TTS（WS 流式 + HTTP）；思考模型后缀；编程套餐 base |
| **deepseek** | `ChannelTypeDeepSeek` | `APITypeDeepSeek` | Y | N | N | – | P | N | – | DeepSeek；OAI 兼容；Top-p 截断、思考模型、Claude 兼容路径 |
| **moonshot** | `ChannelTypeMoonshot` | `APITypeMoonshot` | Y | N | N | – | P | N | – | Moonshot/Kimi；OAI 兼容；用 Claude 适配器处理响应 |
| **mistral** | `ChannelTypeMistral` | `APITypeMistral` | Y | N | N | – | P | N | – | Mistral AI；OAI 兼容；直通 |
| **ollama** | `ChannelTypeOllama` | `APITypeOllama` | Y | N | N | – | P | N | – | Ollama 本地；OAI 兼容；自定义流式 `stream.go` |
| **coze** | `ChannelTypeCoze` | `APITypeCoze` | Y | N | N | – | P | N | – | Coze 字节智能体平台；自定义 chat relay |
| **dify** | `ChannelTypeDify` | `APITypeDify` | Y | N | N | – | P | N | – | Dify；ChatFlow 工作流；自定义 relay |
| **jimeng** | `ChannelTypeJimeng` | `APITypeJimeng` | Y | Y | N | T(jimeng) | N | N | Video+image | 字节即梦；CVProcess API + 自定义签名 |
| **replicate** | `ChannelTypeReplicate` | `APITypeReplicate` | P | Y | N | – | N | N | – | Replicate；图像异步预测 + `Prefer: wait` |
| **codex** | `ChannelTypeCodex` | `APITypeCodex` | N | N | N | – | N | N | – | **仅** `/v1/responses` + `/v1/responses/compact`；OAuth JSON key；`originator: codex_cli_rs`；`chatgpt-account-id` header |
| **siliconflow** | `ChannelTypeSiliconFlow` | `APITypeSiliconFlow` | Y | N | N | – | P | N | – | SiliconFlow；OAI 兼容（Qwen/DeepSeek/GLM/BGE 等开源模型） |
| **xai** | `ChannelTypeXai` | `APITypeXai` | Y | N | N | – | P | N | – | xAI Grok；OAI 兼容；自定义 `text.go` |
| **perplexity** | `ChannelTypePerplexity` | `APITypePerplexity` | Y | N | N | – | P | N | – | Perplexity 搜索增强；OAI 兼容 |
| **mokaai** | `ChannelTypeMokaAI` | `APITypeMokaAI` | Y | N | N | – | P | N | – | Moka AI；OAI 兼容 |
| **submodel** | `ChannelTypeSubmodel` | `APITypeSubmodel` | Y | N | N | – | N | N | – | Submodel 通用代理；**仅 chat**；其它返回 "not supported" |
| **ai360** | `ChannelType360` | (→OpenAI) | P | P | P | – | P | P | – | 360 智脑；无自定义 adaptor；用 `openai.Adaptor{}` |
| **lingyiwanwu** | `ChannelTypeLingYiWanWu` | (→OpenAI) | P | P | P | – | P | P | – | 零一万物 Yi；无自定义 adaptor；用 `openai.Adaptor{}` |
| **openrouter** | `ChannelTypeOpenRouter` | `APITypeOpenRouter` | P | P | P | – | P | P | – | OpenRouter；用 `openai.Adaptor{}` |
| **xinference** | `ChannelTypeXinference` | `APITypeXinference` | P | P | P | – | P | P | – | Xinference（自托管）；用 `openai.Adaptor{}`；针对 bge-reranker、jina-reranker 优化 |

> 旧通道（AILS/AIProxy/OhMyGPT/API2GPT/AIGC2D/AIProxyLibrary/FastGPT/OpenAIMax）常量保留以兼容，不再维护。

#### 3.1.3 异步任务适配器（`relay/channel/task/`）

| Provider | 平台 / ChannelType | 产出 | 计费 | 备注 |
|---|---|---|---|---|
| **suno** | `TaskPlatformSuno` / `ChannelTypeSunoAPI` | 音乐（音频） | BaseBilling | `UpdateSunoTasks` 批量轮询 |
| **sora** | `ChannelTypeSora` / `ChannelTypeOpenAI` | 视频 | 自定义 | OpenAI Sora 视频 |
| **ali** | `ChannelTypeAli` | 视频（通义万相） | 自定义 | DashScope 视频 |
| **kling** | `ChannelTypeKling` | 视频 | 自定义 | 可灵；JWT 鉴权 |
| **jimeng** | `ChannelTypeJimeng` | 视频/图像 | 自定义 | 即梦异步生成 |
| **vertex** | `ChannelTypeVertexAi` | 视频（Veo） | 自定义 | Vertex AI Veo |
| **vidu** | `ChannelTypeVidu` | 视频 | 自定义 | Vidu |
| **doubao** | `ChannelTypeDoubaoVideo` / `ChannelTypeVolcEngine` | 视频 | 自定义 | 豆包视频 |
| **gemini** | `ChannelTypeGemini` | 视频（Veo）+ 图像（Imagen） | 自定义 (`billing.go`) | Gemini 多模态生成 |
| **hailuo** | `ChannelTypeMiniMax` | 视频 | 自定义 | MiniMax Hailuo 视频 |

#### 3.1.4 跨协议转换支持矩阵

| 目标格式 | 已实现 adapter | 备注 |
|----------|----------------|------|
| **Claude (`/v1/messages`)** | ali / aws / baidu_v2 / claude / deepseek / gemini / minimax / moonshot / ollama / openai / perplexity / siliconflow / vertex / volcengine / zhipu_4v | 通过 `ConvertClaudeRequest` 实现；可作为 `/v1/messages` 后端 |
| **Gemini (原生格式)** | gemini | 多数 adaptor 返回 "not implemented" |
| **OpenAI Responses** | openai / codex | codex 仅支持 Responses + Compact |
| **OpenAI Audio** | openai / minimax / volcengine | TTS + Whisper |
| **OpenAI Video** | 全部 task adaptor | 异步，统一转 OpenAI 视频格式 |

### 3.2 接口形态支持

| 形态 | 说明 | 文档 |
|------|------|------|
| `/v1/chat/completions` | OpenAI Chat Completions（支持 OpenAI ↔︎ Claude / Gemini / Responses 转换） | ✅ |
| `/v1/responses` | OpenAI Responses API（GPT-5 系列） | ✅ |
| `/v1/responses/compact` | OpenAI Responses Compact（对话压缩） | ✅ |
| `/v1/images/generations` | 图像生成（支持 `qwen-image`） | ✅ |
| `/v1/images/edits` | 图像编辑（`qwen-image-edit`） | ✅ |
| `/v1/audio/transcriptions` | 音频转录（Whisper） | ✅ |
| `/v1/audio/translations` | 音频翻译 | ✅ |
| `/v1/audio/speech` | TTS 文本转语音 | ✅ |
| `/v1/embeddings` | 文本嵌入 | ✅ |
| `/v1/rerank` | 文档重排序（Cohere/Jina） | ✅ |
| `/v1/moderations` | 内容审核 | ✅ |
| `/v1/realtime` | Realtime WebSocket（含 Azure） | ✅ |
| `/v1/messages` | Anthropic Claude Messages | ✅ |
| `/v1beta/models/{model}:generateContent` | Gemini 原生格式 | ✅ |
| `/v1/video/generations` | 异步视频任务（OpenAI 兼容） | ✅ |
| `/v1/kling/*` | Kling 文/图生视频 | ✅ |
| `/v1/jimeng/*` | 即梦视频 | ✅ |
| `/mj/*` | Midjourney 代理 | ✅ |
| `/suno/*` | Suno 音乐代理 | ✅ |

### 3.3 高级适配特性

- **格式转换矩阵**：OpenAI ↔︎ Claude / Gemini / Responses 双向互转（各 adaptor 的 `ConvertClaudeRequest` / `ConvertOpenAIRequest`，以及 `relay/compatible_handler.go`、`relay/claude_handler.go`）
- **思考转内容**：OpenAI 兼容接口可以选 `reasoning_to_content=true` 把 CoT 折入正文
- **Reasoning Effort 路由**：`o3-mini-high/medium/low`、`gpt-5-high/medium/low`、Claude `-thinking`、`gemini-2.5-*-thinking[-128]` 等后缀语义
- **OpenAI Realtime WebSocket**：原生 `/v1/realtime` 支持，含 Azure
- **流式（SSE）**：`streamSupportedChannels` 控制白名单，默认 OpenAI 协议流
- **Tool / Function Calling**：Claude / OpenAI / Gemini 均支持（含 OpenAI ↔︎ Claude 的 tool schema 转换）
- **Vision（多模态）**：OpenAI `image_url` / Claude `image` / Gemini `inline_data` 三向互通
- **缓存命中计费**：OpenAI / Azure / DeepSeek / Claude / Qwen 等支持 cache hit 单独计费
- **多 Key 轮询**：同一渠道可配置多 Key（`multi_key_mode`），按优先级/权重轮换

---

## 4. 用户与权限体系

### 4.1 三层账户模型

```
User（用户）
   ├─ Group（分组）：default / vip / svip / admin（自定义）
   ├─ Token（令牌）：每个 token 独立额度、模型限制、IP 限制、过期时间
   ├─ Passkey：WebAuthn 凭据
   ├─ 2FA：TOTP 绑定 + 备用码
   └─ OAuth 绑定：GitHub / Discord / LinuxDO / OIDC / WeChat / Telegram

Token（访问令牌）
   ├─ 关联 User + Group
   ├─ 模型白名单 / 黑名单
   ├─ 独立 quota（quota / used_quota / unlimited）
   ├─ 过期时间、状态（enabled）
   └─ IP 段限制、并发限制

Channel（上游渠道）
   ├─ 关联 Group（决定哪些用户能调用）
   ├─ 模型列表（决定该渠道覆盖哪些 model）
   └─ 权重 / 优先级 / 状态
```

### 4.2 用户管理能力

| 能力 | 入口 |
|------|------|
| 用户注册（含邮箱验证、邀请码、密码强度） | `POST /api/user/register` |
| 用户登录（账号密码 / 2FA / Passkey） | `POST /api/user/login` |
| 多端会话管理（查看 / 撤销 / 撤销其他） | `/api/user/sessions/*` |
| 用户自服务（修改信息、注销、查看可用模型） | `/api/user/self/*` |
| 管理员 CRUD 用户 | `/api/user/*` |
| 邀请码（生成 / 转换额度） | `/api/user/invite/*` |
| 搜索用户（按 username/group/status） | `/api/user/search` |
| 管理员重置 Passkey、禁用 2FA | `/api/user/manage` |
| 用户状态管理（启用 / 禁用） | `/api/user/manage` |

### 4.3 分组（Group）与权限

- **预填分组**（`/api/group/prefill`）：批量下发用户时附带默认权限配置
- **分组可用模型范围**：每个 group 有可用模型列表（白名单模式）
- **渠道分组绑定**：每个渠道选择对哪些 group 开放
- **用户分组**：用户绑定一个 group，决定他能用哪些模型
- **公共分组**：`default` 分组允许未登录用户以临时额度体验

### 4.4 令牌（Token）能力

| 维度 | 说明 |
|------|------|
| 模型白/黑名单 | 单 token 限定可调用模型 |
| 额度 | `quota`、`used_quota`、`unlimited` 标记 |
| 过期 | `expired_time` |
| 并发 | `remain_quota` 实时扣减 |
| 状态 | enabled / disabled |
| 查询使用额度 | 配合 `new-api-key-tool` 在客户端展示 |
| 批量管理 | 批量创建/删除/搜索 |
| 使用记录 | 按 token 维度拉取日志 |

---

## 5. 认证与登录方式

### 5.1 登录矩阵

| 方式 | 入口 | 实现 |
|------|------|------|
| 邮箱 + 密码 | `/api/user/login` | `controller/user.go` |
| 邮箱 + 2FA（TOTP） | `/api/user/2fa-login` | `controller/twofa.go` |
| Passkey / WebAuthn | `/api/passkey/login/*` | `controller/passkey.go` |
| GitHub OAuth | `/api/oauth/github` | `oauth/` |
| Discord OAuth | `/api/oauth/discord` | `oauth/` |
| LinuxDO OAuth | `/api/oauth/linuxdo` | `oauth/` |
| OIDC 通用 | `/api/oauth/oidc` | `oauth/` |
| 微信 OAuth | `/api/oauth/wechat` | `oauth/` |
| Telegram 登录 | `/api/oauth/telegram` | `controller/telegram.go` |
| Turnstile 人机验证 | 全局登录/注册 | `middleware/turnstile-check.go` |
| 邮箱验证码 | `/api/verification` | `controller/secure_verification.go`、`middleware/secure_verification.go` |

### 5.2 2FA / Passkey / 安全验证

- **2FA（TOTP）**：
  - 生成二维码、备用码、禁用/启用
  - 强制 2FA（管理员可设置）
  - 登录流程集成
- **Passkey**：
  - 注册、删除、登录（开始/完成）
  - 管理员重置用户 Passkey
- **邮箱验证**：
  - 注册验证、密码重置、邮箱绑定
  - 速率限制（`middleware/email-verification-rate-limit.go`）
- **Turnstile**：Cloudflare Turnstile，可选启用
- **WAF / CC 防护**：body 清理 `middleware/body_cleanup.go`

### 5.3 会话管理

- 多端登录会话列表
- 单端/全端登出
- 会话 token 过期自动续期（区分登录态、token 刷新失败保留登录态，见 commit `17211442`）
- 管理员可撤销指定会话

### 5.4 OAuth State 安全

- `GET /api/oauth/state` 生成 state，前端带 state 回调
- 防 CSRF

---

## 6. 渠道与路由分发

### 6.1 渠道（Channel）抽象

每个上游 API 在 New API 中抽象为一个 **Channel** 记录：

```
Channel {
  id, name,
  type,           // ChannelType* 枚举
  key,            // API key（或多 key JSON）
  base_url,       // 自定义 endpoint
  model_mapping,  // 模型重定向
  groups,         // 对哪些 group 开放
  weight,         // 路由权重
  priority,       // 同 model 多个 channel 时的优先级
  status,         // enabled / disabled / auto
  balance,        // 上游余额（部分渠道）
  settings_json,  // 渠道特定参数（如 gemini safety）
  tag,            // 多 Key 模式下的标签
  ...
}
```

### 6.2 路由策略

| 策略 | 实现位置 | 说明 |
|------|----------|------|
| 加权随机 | `middleware/distributor.go` | 按 `weight` 概率分配 |
| 优先级 | 同上 | 同 `model` 多渠道按 `priority` 选 |
| 失败自动重试 | `relay/relay_adaptor.go`、`relay/relay_task.go` + 重试机制 | 同 `model` 多个候选时按序回退 |
| 渠道缓存 | `model/channel_cache.go` | 内存 + Redis，定时同步 |
| 渠道亲和（Affinity） | `service/channel_affinity.go`、`controller/channel_affinity_cache.go` | 同用户/会话粘到同一上游 |
| 自动修复能力 | `POST /api/channel/fix` | 自动尝试补齐缺失 model |
| 多 Key 模式 | `multi_key_mode`（constant/multi_key_mode.go） | 单渠道多 Key 轮换/独立 |
| 渠道测试 | `/api/channel/test*` | 全部 / 指定 |
| 渠道余额同步 | `/api/channel/update_balance*` | 拉取上游剩余额度 |
| 标签（Tag）管理 | `/api/channel/tag/*` | 启用/禁用/编辑/复制 |

### 6.3 模型重定向

- **Model Mapping**：渠道级别把客户端请求的 `gpt-4` 改写到上游实际模型 `gpt-4-0613`
- **Missing Models 检测**：`/api/channel/missing_models` 自动发现尚未被任何渠道覆盖的 model
- **上游模型同步**：`/api/channel/sync_models` 主动拉上游模型列表

### 6.4 分发链路

```
请求 /v1/chat/completions
   │
   ▼
middleware/auth.go（解析 Token）
   │
   ▼
service.Distribute(channel-cache, token, model)
   │
   ├─ 过滤 group 不匹配的渠道
   ├─ 过滤 model 不覆盖的渠道
   ├─ 按 priority 升序 / weight 加权随机
   ├─ 应用 channel_affinity
   └─ 选出候选渠道列表
   │
   ▼
relay/relay_adaptor.go → RerunRequest（DoRequest）
   │
   ├─ 失败 → ReloadSpecificChannelsAbilities → 选下一个
   └─ 成功 → DoResponse → 流式回写 + 计费
```

---

## 7. 计费表达式与配额系统

### 7.1 配额数据模型

- **quota**：抽象计费单位，1 美元 = `common.QuotaPerUnit`（默认 500000）quota（common/constants.go:22），所有 quota 相关字段均为 Go 原生 `int`（model/user.go、model/log.go、model/token.go）
- **user.quota**：用户余额
- **token.quota / used_quota**：令牌独立额度
- **log.quota / log.usage_quota**：每次请求的扣费快照

### 7.2 计费模式

#### 7.2.1 按倍率（Ratio）

`setting/ratio_setting/` 提供多档倍率（**所有倍率源头只有"模型倍率 + 分组倍率 + 分组对分组倍率"三层，无 user_ratio / channel_ratio 字段**）：

| 倍率类型 | 文件 | 说明 |
|----------|------|------|
| 模型倍率（输入） | `model_ratio.go:defaultModelRatio` | 每个 model 一个浮点倍率 |
| 模型补全倍率（输出） | `model_ratio.go:completionRatioMap` | 输出 token 倍率 |
| 缓存命中倍率 | `cache_ratio.go:defaultCacheRatio` | cache hit 折扣倍率 |
| 缓存写入倍率 | `cache_ratio.go:defaultCreateCacheRatio` | cache write 单独计费倍率 |
| 图像倍率 | `model_ratio.go:defaultImageRatio` | 多模态图像 token 倍率 |
| 音频输入倍率 | `model_ratio.go:defaultAudioRatio` | 音频 token 输入倍率 |
| 音频输出倍率 | `model_ratio.go:defaultAudioCompletionRatio` | 音频 token 输出倍率 |
| 分组倍率 | `group_ratio.go:defaultGroupRatio` | 每个 group 一个倍率（default / vip / svip / 自定义） |
| 分组对分组倍率 | `group_ratio.go:defaultGroupGroupRatio` | 二维矩阵 `userGroup × usingGroup → ratio`，覆盖分组倍率 |

**用户模型上没有 ratio / discount 字段**——差异化只通过"用户 → 分组"承载。

最终扣费公式：

```text
group_ratio 由 relay/helper/price.go 的 HandleGroupRatio（约 :20-46） 决定：
  若 GetGroupGroupRatio(userGroup, usingGroup) 命中 → 覆盖为该值；
  否则 → GetGroupRatio(usingGroup)。
ratio = model_ratio × group_ratio
```

OpenAI/通用格式（relay/compatible_handler.go 约 :336-408，shopspring/decimal 精确计算）：

```text
ratio = model_ratio × group_ratio
base = prompt_tokens − cache_tokens − cache_create_tokens − image_tokens − audio_tokens（仅非 Claude 语义时减）
prompt_quota    = base + cache_tokens×cache_ratio + cache_create_tokens×cache_create_ratio + image_tokens×image_ratio
completion_quota = completion_tokens × completion_ratio
quota = (prompt_quota + completion_quota) × ratio
       + gemini_audio_input(按 1M token 独立价)
       + web_search / file_search / image_generation_call 调用计费（各自独立累加）
```

Claude Messages 格式（service/quota.go 的 PostClaudeConsumeQuota，约 :275-289，区分 5m/1h 缓存写入）：

```text
quota = prompt_tokens
      + cache_tokens × cache_ratio
      + cache_creation_5m × cache_creation_ratio_5m
      + cache_creation_1h × cache_creation_ratio_1h
      + remaining_creation × cache_creation_ratio
      + completion_tokens × completion_ratio
quota = quota × group_ratio × model_ratio
```

其中 cache_creation_ratio_1h = cache_creation_ratio × (6/3.75)（relay/helper/price.go 约 :17），默认 5m 基准 1.25 ⇒ 1h ≈ 2.0。

固定价模型（quota_type=1，DALL-E/MJ/Suno）：`quota = model_price × QuotaPerUnit × group_ratio`，不走 token 倍率（relay/helper/price.go 约 :96、service/quota.go 约 :288）。quota_type 由 model/pricing.go 约 :298-303 从 use_price 派生。

#### 7.2.2 表达式计费

> 注：早期文档曾引用 `pkg/billingexpr` 与 `expr.md`，但代码库中**不存在**该包/文件，也不存在 `QuotaFromFloat` / `QuotaRound` / `QuotaFromDecimal` 等函数。newapi 当前没有独立的"表达式计费"模块；差异化定价通过 `model_ratio` / `completion_ratio` / `cache_ratio` / `image_ratio` / `audio_ratio` 等倍率配置实现（见 §7.2.1）。

### 7.3 安全不变式

- 配额不会因计算产生负数：OpenAI 路径与 Claude 路径在 ratio 非零但计算结果 ≤0 时，会内联置为 1（relay/compatible_handler.go 约 :386-388、service/quota.go 约 :291-293）；这是内联逻辑，不是独立函数，也没有专门的审计事件。
- 所有"乘数"字段（image n、video seconds、resolution、batch count）在请求校验处 clamp。
- 上游 deduction（如 Kling FinalUnitDeduction）在各自 task adaptor 内饱和。
- 注意：代码中不存在 quota_math.go / QuotaClamp / attachQuotaSaturation / quota_saturation 审计字段；`log.other.admin_info` 实际只记录 use_channel、is_multi_key、local_count_tokens、channel_affinity 等（service/log_info_generate.go）。

### 7.4 预扣与结算流程

```
请求进入 → 估算可能扣费 → PreConsume（预扣 token.quota + user.quota）
   │
   ▼
relay → 上游响应 → 实际使用 token 数 → BillingPreciseQuota / EstimateBilling
   │
   ▼
Settle（差额结算）：补扣或部分退还（退款走 task refund 路径）
```

### 7.5 价格系统

- **模型定价（pricing）**：`model/pricing.go`、`controller/pricing.go`、`model/pricing_refresh.go`
- **默认价格**：`pricing_default.go`
- **缺失模型同步**：`controller/missing_models.go`
- **倍率同步**：`controller/ratio_sync.go`、`dto/ratio_sync.go`
- **价格接口**：`/api/pricing`、`/api/pricing/refresh`
- **上游倍率**：`/api/pricing/sync` 把上游计费规则同步进来

---

## 8. 充值与支付订阅

### 8.1 充值方式

| 方式 | 文件 | 备注 |
|------|------|------|
| 易支付（epay） | controller/topup.go、service/epay.go | 国内：支付宝/微信/QQ 钱包；回调 /api/user/epay/notify |
| Stripe | controller/topup_stripe.go、setting/payment_stripe.go | 海外信用卡；回调 /api/stripe/webhook |
| Creem | controller/topup_creem.go | 海外新兴支付；回调 /api/creem/webhook |
| 兑换码（Redemption） | controller/redemption.go、model/redemption.go | 卡密兑换，管理员生成 |
| 管理员手动充值 | /api/user/topup | 内部赠送 |
| 邀请码额度转换 | /api/user/aff_transfer | 邀请返佣 |

### 8.2 订阅（Subscription）

- 订阅计划由管理员配置
- 周期内配额、定时重置（`subscription_reset_task.go`）
- 自动续期与失败降级
- Webhook：Stripe / Creem / epay 异步通知
- 可绑定支付方式：易支付（epay）、Stripe、Creem

---

## 9. 后台管理与运营

### 9.1 仪表盘（Dashboard）

- `/api/dashboard/*`：系统总览、用户/渠道/调用量趋势、收入曲线
- 数据看板依赖 `controller/usedata.go`、`model/usedata.go`、`controller/performance.go`、`setting/performance_setting/`

### 9.2 管理接口分组（共 17 类，源自 `docs/openapi/api.json`）

| 分组 | 数量 | 主要端点 |
|------|------|----------|
| 系统 | 11 | 状态、初始化、Uptime Kuma、公告、协议、关于、首页、定价、模型列表、倍率配置 |
| 用户登录注册 | 6 | 注册、登录、2FA 登录、会话、密码重置 |
| OAuth | 10+ | GitHub/Discord/OIDC/LinuxDO/WeChat/Telegram |
| 用户管理 | 12+ | CRUD、搜索、状态、邀请码 |
| 充值 | 9 | 易支付/Stripe/Creem、Webhook、回调 |
| 两步验证 | 6 | TOTP 状态、启用/禁用、备用码、统计 |
| 安全验证 | 4 | Turnstile、邮箱验证码 |
| 渠道管理 | 17+ | CRUD、测试、余额、同步、Tag、多 Key |
| 令牌管理 | 8 | CRUD、搜索、使用情况 |
| 兑换码 | 7 | CRUD、清理 |
| 日志 | 8 | 全部/个人日志、统计、清理 |
| 数据统计 | 4 | 额度、排行 |
| 分组 | 5 | 预填分组 |
| 任务 | 4 | Midjourney/通用任务查询 |
| 供应商 | 6 | CRUD |
| 模型管理 | 7 | 元数据、缺失模型、同步 |
| 系统设置 | 6 | 选项、模型倍率重置 |

### 9.3 系统设置（Operation / System）

存储于 `model/option.go`：

- **站点基础**：站点名、Logo、备案号、公告、关于、首页内容
- **注册策略**：是否开放注册、是否需要邀请码、是否需要邮箱验证
- **登录策略**：是否启用 2FA、是否允许 Passkey、OAuth 启用矩阵
- **支付策略**：各支付方式启用、密钥
- **安全策略**：Turnstile、WAF、IP 黑/白名单、Trusted Proxies
- **额度策略**：注册赠送、邀请返佣、一键签到、签到赠送
- **运维策略**：日志保留天数、统计刷新频率、性能开关

### 9.4 预填分组（Prefill Group）

管理员在创建用户时预设：分组、初始额度、可用模型、令牌模板。

### 9.5 模型元数据管理

- 自定义模型显示名、Owned-By、Tag
- 同步上游模型列表
- 缺失模型检测

### 9.6 供应商（Vendor）管理

为多渠道分组：把同一厂商的多个渠道统一管理（标签、限额、告警）。

---

## 10. 可观测、日志与审计

### 10.1 日志类型

| 类型 | 表 / 存储 | 说明 |
|------|-----------|------|
| 请求日志（RequestLog） | `model/log.go` | 每次调用的：模型、用量、quota、客户端 IP、耗时、错误码 |
| 消耗日志（Log） | 同上 | 用户/渠道维度聚合账单 |
| 系统日志 | `common.SysLog` | 启动、缓存同步、任务调度 |

### 10.2 个人 vs 全局日志

- 用户只能拉取自己的日志（`/api/log/self`）
- 管理员可拉全量（`/api/log`）并按 token / 用户 / 模型筛选

### 10.3 统计与排行

- 排行榜：`controller/usedata.go`（按 token / 消费 / 调用次数）
- 用量统计：`controller/usedata.go`、`model/usedata.go`（按日/周/月聚合）
- 性能指标：`controller/performance.go`、`setting/performance_setting/`（请求 P50/P99、错误率）
- Uptime Kuma 探针：`controller/uptime_kuma.go`

### 10.4 任务进度追踪

- Midjourney / Suno / Kling / Jimeng / Vidu 任务都有进度查询接口
- `/mj/*` `/suno/*` `/v1/video/generations/{id}` 路径
- 任务结算、失败退款：`service/task_polling.go`、`service/task_billing.go`

---

## 11. 安全与速率限制

### 11.1 速率限制（中间件）

| 中间件 | 作用 |
|--------|------|
| `middleware/rate-limit.go` | 全局限流（IP / 用户维度） |
| `middleware/model-rate-limit.go` | 模型级别限流 |
| `middleware/email-verification-rate-limit.go` | 邮件验证码防刷 |
| `middleware/turnstile-check.go` | Cloudflare Turnstile |
| `middleware/auth.go` | 鉴权统一入口 |

### 11.2 防滥用

- **WAF**：body 清洗 `middleware/body_cleanup.go`、敏感词 `service/sensitive.go`
- **缓存控制**：`middleware/disable-cache.go`（防止敏感响应被缓存）
- **分布式限流**：Redis 令牌桶 / 滑动窗口
- **CC 防护**：审计 + 限流组合
- **Trusted Proxies**：可配置的代理链白名单（`trusted_proxies.go`）

### 11.3 加密与签名

- JWT / 会话：`middleware/auth.go`（authHelper）、`controller/user.go`（Login/会话）
- 凭据加密存储（API Key 在 DB 中可加密）
- 加密响应：`service/http.go` 提供 response 加密选项

### 11.4 安全合规

- 敏感词过滤：`service/sensitive.go`
- 内容审核：转发 `moderations` 接口到上游
- 用户违规扣费：`service/violation_fee.go`
- 安全验证：`controller/secure_verification.go`

---

## 12. 前端能力

### 12.1 技术栈

- React 18 + TypeScript
- Vite 构建工具
- Semi Design（@douyinfe/semi-ui，组件库）
- Tailwind CSS（辅助样式工具）
- i18next + react-i18next（国际化）
- Bun 包管理器（推荐）

### 12.2 用户端

- 登录 / 注册 / 找回密码（含 2FA / Passkey）
- 控制台：余额、用量、API Key 管理
- 模型广场：可调用模型列表、定价
- 充值：易支付/Stripe/Creem
- 订阅管理
- 邀请码 / 兑换码
- 个人日志、消费明细
- 设置：个人信息、安全

### 12.3 管理端

- Dashboard 总览
- 用户管理（CRUD、搜索、状态、邀请、充值）
- 渠道管理（CRUD、测试、余额、同步）
- 令牌管理
- 兑换码管理
- 分组管理
- 模型/供应商管理
- 日志查询（全局 / 个人）
- 排行榜 / 统计
- 系统设置（站点、注册、登录、支付、安全、运维）
- 任务管理（Midjourney / Suno / 视频）

### 12.4 多语言

- 前端支持：zh-CN（基础）、zh、en（fallback）、zh-TW、fr、ru、ja、vi
- 后端支持：en、zh
- 文件位置：`web/src/i18n/locales/*.json`
- 工具：`bun run i18n:sync`（同步新 key）

### 12.5 主题与定制

- `web/src/` 内置主题与品牌定制
- 站点 Logo、首页内容、关于、协议均可后台编辑
- 公告支持 Markdown

---

## 13. 辅助能力（OAuth / 邮件 / Passkey / 文件 / 缓存）

### 13.1 OAuth 提供商

- GitHub（`oauth/github.go`）
- Discord
- LinuxDO
- OIDC（通用）
- 微信
- Telegram
- 自定义 OAuth（`controller/custom_oauth.go`、`model/custom_oauth_provider.go`）

### 13.2 邮件

- SMTP 发送（注册验证、密码重置、绑定）
- 邮件验证码 + 速率限制
- 邮件模板可配置

### 13.3 Passkey / WebAuthn

- 注册 / 删除 / 登录
- 多 Passkey 支持
- 管理员可重置用户 Passkey

### 13.4 文件存储

- 文件解码：`service/file_decoder.go`
- 文件服务：`service/file_service.go`
- 上传 / 下载代理
- 支持 OpenAI `files` 接口（部分）

### 13.5 缓存

- **内存缓存**：`common.MemoryCacheEnabled`（`channel` 缓存、定价缓存、用户缓存）
- **Redis**：`common.RedisEnabled`（分布式限流、分布式锁、session 存储）
- **定时同步**：`model.SyncChannelCache(common.SyncFrequency)`
- **冷启动**：首次请求时回源、panic-safe 重试

### 13.6 性能

- 性能指标采集：`controller/performance.go`、`setting/performance_setting/`
- 性能开关：`setting/performance_setting/`
- 渠道缓存预热 + 修复能力
- 优雅关闭 + 信号处理

### 13.7 数据库迁移

- **GORM AutoMigrate**：所有 model 自动建表
- **跨方言**：SQLite/MySQL/PostgreSQL 均支持
- **种子数据**：`model/setup.go` 初始化 root 管理员、默认分组、默认模型
- **PG/MySQL 关键字引号**：`commonGroupCol`、`commonKeyCol`
- **布尔列兼容**：避免 `gorm default:true` 触发的多余 ALTER TABLE（已实践）

### 13.8 Electron 桌面客户端

- `electron/` 目录：可打包为桌面应用
- 调用本地 New API 后端

---

## 14. 运维与部署

### 14.1 部署形态

| 形态 | 文件 |
|------|------|
| Docker | `Dockerfile`、`docker-compose.yml` |
| 开发 Docker | `Dockerfile.dev`、`docker-compose.dev.yml` |
| 二进制 | `bin/` |
| 服务注册 | `new-api.service`（systemd） |
| 桌面端 | `electron/` |

### 14.2 环境变量（节选）

详见 README：
- `REDIS_CONN_STRING`、`SYNC_FREQUENCY`
- `SQLITE_PATH`、`MYSQL_DSN`、`PG_DSN`
- `GIN_MODE`、`DEBUG`
- `FRONTEND_BASE_URL`（前后端分离部署）
- `TURNSTILE_SITE_KEY / SECRET`
- 各 OAuth/支付 Key

### 14.3 多机部署

- Redis 必选（分布式锁 / 限流 / 缓存）
- Master-Worker 节点模式（`IsMasterNode`）
- `FRONTEND_BASE_URL` 在 master 节点被忽略

### 14.4 渠道重试与缓存策略

详见 README：缓存 channel 减少 DB 压力、自动重试下一渠道、冷启动修复。

### 14.5 监控接入

- Uptime Kuma 状态探针（`/api/status`）
- Prometheus-friendly perf metrics 入口
- pprof：debug 模式自动开启

---

## 15. API 接口概览

### 15.1 鉴权层级（Auth Layers）

系统按强度递增提供以下中间件，组合使用：

| 中间件 | 作用 |
|--------|------|
| `None` | 完全公开（如 `/api/setup`、`/api/notice`） |
| `TurnstileCheck` | Cloudflare Turnstile 反爬虫 |
| `GlobalAPIRateLimit` | 全局限流 |
| `CriticalRateLimit` | 严格限流（敏感操作） |
| `TokenAuth` | Token header 鉴权（兼容旧 Dashboard） |
| `TokenAuthReadOnly` | Token 只读（usage 查询） |
| `TokenOrUserAuth` | Token 或 Session（视频代理） |
| `UserAuth` | Session 用户鉴权 |
| `TryUserAuth` | 尝试鉴权（OAuth State 可选） |
| `AdminAuth` | 管理员鉴权 |
| `RootAuth` | 超级管理员鉴权 |
| `SecureVerificationRequired` | 已通过安全验证（邮箱/2FA） |
| `Distribute` | 请求分发中间件（relay 层） |
| `KlingRequestConvert` / `JimengRequestConvert` | 上游请求格式转换 |

newapi 采用数字 role 权限模型（common/constants.go 约 :140-145）：RoleGuestUser=0、RoleCommonUser=1、RoleAdminUser=10、RoleRootUser=100。鉴权中间件 middleware/auth.go 通过 authHelper(c, minRole) 比较 role ≥ minRole，提供 UserAuth()（≥1）、AdminAuth()（≥10）、RootAuth()（≥100），以及 TokenAuth / TokenAuthReadOnly / TokenOrUserAuth / TryUserAuth。无细粒度 RBAC。

### 15.2 AI 代理接口（docs/openapi/relay.json）

完整定义在 `docs/openapi/relay.json`。

#### 15.2.1 OpenAI 兼容 `/v1`

| Method | Path | Controller Function | 用途 |
|--------|------|---------------------|------|
| GET | `/v1/models` | `ListModels` (OpenAI) | 列出可用模型 |
| GET | `/v1/models/:model` | `RetrieveModel` (OpenAI) | 单个模型详情 |
| POST | `/v1/completions` | `Relay` (OpenAI) | Legacy Text Completions |
| POST | `/v1/chat/completions` | `Relay` (OpenAI) | 聊天对话 |
| POST | `/v1/embeddings` | `Relay` (Embedding) | 文本嵌入 |
| POST | `/v1/edits` | `Relay` (OpenAIImage) | 图像编辑（legacy） |
| POST | `/v1/images/generations` | `Relay` (OpenAIImage) | 图像生成 |
| POST | `/v1/images/edits` | `Relay` (OpenAIImage) | 图像编辑 |
| POST | `/v1/images/variations` | `RelayNotImplemented` | 图像变体（占位） |
| POST | `/v1/audio/transcriptions` | `Relay` (OpenAIAudio) | 音频转录 |
| POST | `/v1/audio/translations` | `Relay` (OpenAIAudio) | 音频翻译 |
| POST | `/v1/audio/speech` | `Relay` (OpenAIAudio) | TTS |
| POST | `/v1/moderations` | `Relay` (OpenAI) | 内容审核 |
| POST | `/v1/rerank` | `Relay` (Rerank) | 重排序 |
| POST | `/v1/responses` | `Relay` (OpenAIResponses) | Responses API |
| POST | `/v1/responses/compact` | `Relay` (OpenAIResponsesCompaction) | Responses 对话压缩 |
| GET | `/v1/realtime` | `Relay` (OpenAIRealtime) | Realtime WebSocket |

#### 15.2.2 Anthropic 兼容 `/v1`

| Method | Path | Controller Function | 用途 |
|--------|------|---------------------|------|
| GET | `/v1/models`（带 `anthropic-version` header） | `ListModels` (Anthropic) | 列出 Claude 模型 |
| GET | `/v1/models/:model`（带 `anthropic-version` header） | `RetrieveModel` (Anthropic) | Claude 模型详情 |
| POST | `/v1/messages` | `Relay` (Claude) | Claude Messages API |

#### 15.2.3 Gemini 兼容

| Method | Path | Controller Function | 用途 |
|--------|------|---------------------|------|
| GET | `/v1/models`（带 `x-goog-api-key`） | `RetrieveModel` (Gemini) | 列出 Gemini 模型 |
| GET | `/v1beta/models` | `ListModels` (Gemini) | Gemini 模型列表 |
| GET | `/v1beta/openai/models` | `ListModels` (OpenAI) | Gemini 端点上的 OpenAI 兼容模型 |
| POST | `/v1beta/models/*path` | `Relay` (Gemini) | Gemini 原生 Relay |
| POST | `/v1/models/*path` | `Relay` (Gemini) | Gemini 路径在 /v1 下 |
| POST | `/v1/engines/:model/embeddings` | `Relay` (Gemini) | Gemini 嵌入 |

#### 15.2.4 Playground

| Method | Path | Controller Function | 用途 |
|--------|------|---------------------|------|
| POST | `/pg/chat/completions` | `Playground` | Playground 试用（UserAuth） |

#### 15.2.5 Midjourney 代理

| Method | Path | Controller Function | 用途 |
|--------|------|---------------------|------|
| GET | `/mj/image/:id` | `RelayMidjourneyImage` | 提供 MJ 图像 |
| POST | `/mj/submit/action` | `RelayMidjourney` | 提交 MJ 动作 |
| POST | `/mj/submit/shorten` | `RelayMidjourney` | 提交 shorten |
| POST | `/mj/submit/modal` | `RelayMidjourney` | 提交 modal |
| POST | `/mj/submit/imagine` | `RelayMidjourney` | 提交 imagine |
| POST | `/mj/submit/change` | `RelayMidjourney` | 提交 change |
| POST | `/mj/submit/simple-change` | `RelayMidjourney` | simple-change |
| POST | `/mj/submit/describe` | `RelayMidjourney` | 描述生成 |
| POST | `/mj/submit/blend` | `RelayMidjourney` | blend 混合 |
| POST | `/mj/submit/edits` | `RelayMidjourney` | 编辑 |
| POST | `/mj/submit/video` | `RelayMidjourney` | 视频生成 |
| GET | `/mj/task/:id/fetch` | `RelayMidjourney` | 任务查询 |
| GET | `/mj/task/:id/image-seed` | `RelayMidjourney` | 图像 seed |
| POST | `/mj/task/list-by-condition` | `RelayMidjourney` | 列表 |
| POST | `/mj/insight-face/swap` | `RelayMidjourney` | 换脸 |
| POST | `/mj/submit/upload-discord-images` | `RelayMidjourney` | 上传 Discord 图像 |

> 上述所有路由同时支持 `/:mode/mj` 前缀（多 mode 隔离）。

#### 15.2.6 Suno 代理

| Method | Path | Controller Function | 用途 |
|--------|------|---------------------|------|
| POST | `/suno/submit/:action` | `RelayTask` | 提交 Suno 任务 |
| POST | `/suno/fetch` | `RelayTaskFetch` | 批量查询 |
| GET | `/suno/fetch/:id` | `RelayTaskFetch` | 单个查询 |

#### 15.2.7 视频代理

| Method | Path | Controller Function | 用途 |
|--------|------|---------------------|------|
| POST | `/v1/video/generations` | `RelayTask` | 生成视频 |
| GET | `/v1/video/generations/:task_id` | `RelayTaskFetch` | 视频任务状态 |
| GET | `/v1/videos/:task_id/content` | `VideoProxy` | 视频内容代理（TokenOrUserAuth） |
| POST | `/v1/videos/:video_id/remix` | `RelayTask` | 视频 remix |
| POST | `/v1/videos` | `RelayTask` | 创建视频（OpenAI 兼容） |
| GET | `/v1/videos/:task_id` | `RelayTaskFetch` | OpenAI 兼容查询 |
| POST | `/kling/v1/videos/text2video` | `RelayTask` | Kling 文生视频 |
| POST | `/kling/v1/videos/image2video` | `RelayTask` | Kling 图生视频 |
| GET | `/kling/v1/videos/text2video/:task_id` | `RelayTaskFetch` | Kling 文生视频查询 |
| GET | `/kling/v1/videos/image2video/:task_id` | `RelayTaskFetch` | Kling 图生视频查询 |
| POST | `/jimeng/` | `RelayTask` | 即梦视频生成 |

#### 15.2.8 Dashboard Billing（兼容旧版）

| Method | Path | Controller Function | 用途 |
|--------|------|---------------------|------|
| GET | `/dashboard/billing/subscription` | `GetSubscription` | 订阅信息 |
| GET | `/v1/dashboard/billing/subscription` | `GetSubscription` | 同上 |
| GET | `/dashboard/billing/usage` | `GetUsage` | 用量信息 |
| GET | `/v1/dashboard/billing/usage` | `GetUsage` | 同上 |

#### 15.2.9 占位（NotImplemented）

以下 OpenAI 路径返回 `RelayNotImplemented`：`/v1/files`（list/create/get/delete/content）、`/v1/fine-tunes`（list/create/get/cancel/events）、`DELETE /v1/models/:model`。

### 15.3 管理接口（docs/openapi/api.json）

#### 15.3.1 系统 / 状态

| Method | Path | Auth | Controller | 用途 |
|--------|------|------|------------|------|
| GET | `/api/setup` | none | `GetSetup` | 获取初始化状态 |
| POST | `/api/setup` | none | `PostSetup` | 初始化系统 |
| GET | `/api/status` | none | `GetStatus` | 系统状态 |
| GET | `/api/status/test` | AdminAuth | `TestStatus` | 测试状态 |
| GET | `/api/uptime/status` | none | `GetUptimeKumaStatus` | Uptime Kuma 集成 |
| GET | `/api/notice` | none | `GetNotice` | 系统公告 |
| GET | `/api/user-agreement` | none | `GetUserAgreement` | 用户协议 |
| GET | `/api/privacy-policy` | none | `GetPrivacyPolicy` | 隐私政策 |
| GET | `/api/about` | none | `GetAbout` | 关于 |
| GET | `/api/home_page_content` | none | `GetHomePageContent` | 首页内容 |
| GET | `/api/pricing` | module auth | `GetPricing` | 定价 |
| GET | `/api/models` | UserAuth | `DashboardListModels` | 仪表盘模型 |
| GET | `/api/ratio_config` | rate limit | `GetRatioConfig` | 倍率配置 |

#### 15.3.2 性能指标 / 排行

| Method | Path | Auth | Controller | 用途 |
|--------|------|------|------------|------|
| GET | `/api/perf-metrics/summary` | public/user | `GetPerfMetricsSummary` | 性能摘要 |
| GET | `/api/perf-metrics` | public/user | `GetPerfMetrics` | 性能详情 |
| GET | `/api/rankings` | module auth | `GetRankings` | 用户排行 |

#### 15.3.3 验证 / 密码重置

| Method | Path | Auth | Controller | 用途 |
|--------|------|------|------------|------|
| GET | `/api/verification` | RL+TS | `SendEmailVerification` | 邮箱验证码 |
| GET | `/api/reset_password` | RL+TS | `SendPasswordResetEmail` | 密码重置邮件 |
| POST | `/api/user/reset` | rate limit | `ResetPassword` | 重置密码 |

#### 15.3.4 OAuth / 回调 / Webhook

| Method | Path | Auth | Controller | 用途 |
|--------|------|------|------------|------|
| POST | `/api/oauth/state` | TryUserAuth | `GenerateOAuthCode` | 生成 OAuth state |
| POST | `/api/oauth/email/bind` | UserAuth | `EmailBind` | 绑定邮箱 |
| GET | `/api/oauth/wechat` | rate limit | `WeChatAuth` | 微信 OAuth 登录 |
| POST | `/api/oauth/wechat/bind` | UserAuth | `WeChatBind` | 绑定微信 |
| GET | `/api/oauth/telegram/login` | rate limit | `TelegramLogin` | Telegram 登录 |
| POST | `/api/oauth/telegram/bind/start` | UserAuth | `TelegramBindStart` | 启动绑定 |
| GET | `/api/oauth/telegram/bind/:flow_token` | rate limit | `TelegramBind` | 完成绑定 |
| GET | `/api/oauth/:provider` | TryUserAuth | `HandleOAuth` | 通用 OAuth（GitHub/Discord/OIDC/LinuxDO） |
| POST | `/api/verify` | UserAuth | `UniversalVerify` | 通用安全验证 |
| POST | `/api/stripe/webhook` | public | `StripeWebhook` | Stripe 回调 |
| POST | `/api/creem/webhook` | public | `CreemWebhook` | Creem 回调 |

#### 15.3.5 用户路由（未认证）

| Method | Path | Auth | Controller | 用途 |
|--------|------|------|------------|------|
| POST | `/api/user/auth/refresh` | cookie guard | `RefreshAuth` | 刷新 session |
| POST | `/api/user/auth/logout` | cookie guard | `AuthLogout` | 登出 |
| POST | `/api/user/register` | RL+TS | `Register` | 注册 |
| POST | `/api/user/login` | RL+TS | `Login` | 登录 |
| POST | `/api/user/login/2fa` | rate limit | `Verify2FALogin` | 2FA 登录 |
| POST | `/api/user/passkey/login/begin` | rate limit | `PasskeyLoginBegin` | Passkey 登录开始 |
| POST | `/api/user/passkey/login/finish` | rate limit | `PasskeyLoginFinish` | Passkey 登录完成 |
| POST | `/api/user/epay/notify` | none | `EpayNotify` | 易支付回调（POST） |
| GET | `/api/user/epay/notify` | none | `EpayNotify` | 易支付回调（GET） |
| GET | `/api/user/groups` | none | `GetUserGroups` | 用户分组列表 |

#### 15.3.6 用户自服务（UserAuth）

| Method | Path | Controller | 用途 |
|--------|------|------------|------|
| GET | `/api/user/sessions` | `GetLoginSessions` | 登录会话列表 |
| DELETE | `/api/user/sessions/:sid` | `DeleteLoginSession` | 删除会话 |
| POST | `/api/user/sessions/revoke-others` | `RevokeOtherLoginSessions` | 撤销其他会话 |
| GET | `/api/user/self/groups` | `GetUserGroups` | 当前分组 |
| GET | `/api/user/self` | `GetSelf` | 当前用户信息 |
| GET | `/api/user/models` | `GetUserModels` | 可用模型 |
| PUT | `/api/user/self` | `UpdateSelf` | 更新个人信息 |
| DELETE | `/api/user/self` | `DeleteSelf` | 注销 |
| GET | `/api/user/token` | `GenerateAccessToken` | 生成访问令牌 |
| GET | `/api/user/passkey` | `PasskeyStatus` | Passkey 状态 |
| POST | `/api/user/passkey/register/begin` | `PasskeyRegisterBegin` | Passkey 注册开始 |
| POST | `/api/user/passkey/register/finish` | `PasskeyRegisterFinish` | Passkey 注册完成 |
| POST | `/api/user/passkey/verify/begin` | `PasskeyVerifyBegin` | Passkey 验证开始 |
| POST | `/api/user/passkey/verify/finish` | `PasskeyVerifyFinish` | Passkey 验证完成 |
| DELETE | `/api/user/passkey` | `PasskeyDelete` | 删除 Passkey |
| GET | `/api/user/aff` | `GetAffCode` | 邀请码 |
| POST | `/api/user/aff_transfer` | `TransferAffQuota` | 邀请额度转换 |
| PUT | `/api/user/setting` | `UpdateUserSetting` | 更新设置 |

#### 15.3.7 2FA / 签到 / OAuth 绑定

| Method | Path | Controller | 用途 |
|--------|------|------------|------|
| GET | `/api/user/2fa/status` | `Get2FAStatus` | 2FA 状态 |
| POST | `/api/user/2fa/setup` | `Setup2FA` | 设置 2FA |
| POST | `/api/user/2fa/enable` | `Enable2FA` | 启用 2FA |
| POST | `/api/user/2fa/disable` | `Disable2FA` | 禁用 2FA |
| POST | `/api/user/2fa/backup_codes` | `RegenerateBackupCodes` | 重新生成备用码 |
| GET | `/api/user/checkin` | `GetCheckinStatus` | 签到状态 |
| POST | `/api/user/checkin` | `DoCheckin` | 每日签到 |
| GET | `/api/user/oauth/bindings` | `GetUserOAuthBindings` | OAuth 绑定列表 |
| DELETE | `/api/user/oauth/bindings/:provider_id` | `UnbindCustomOAuth` | 解绑 |

#### 15.3.8 充值 / 支付（UserAuth）

| Method | Path | Controller | 用途 |
|--------|------|------------|------|
| GET | `/api/user/topup/info` | `GetTopUpInfo` | 充值选项 |
| GET | `/api/user/topup/self` | `GetUserTopUps` | 个人充值记录 |
| POST | `/api/user/topup` | `TopUp` | 兑换充值码 |
| POST | `/api/user/pay` | `RequestEpay` | 易支付 |
| POST | `/api/user/amount` | `RequestAmount` | 请求金额 |
| POST | `/api/user/stripe/pay` | `RequestStripePay` | Stripe 支付 |
| POST | `/api/user/stripe/amount` | `RequestStripeAmount` | Stripe 金额 |
| POST | `/api/user/creem/pay` | `RequestCreemPay` | Creem 支付 |

#### 15.3.9 管理员用户管理（AdminAuth）

| Method | Path | Controller | 用途 |
|--------|------|------------|------|
| GET | `/api/user/` | `GetAllUsers` | 用户列表 |
| GET | `/api/user/topup` | `GetAllTopUps` | 充值记录列表 |
| POST | `/api/user/topup/complete` | `AdminCompleteTopUp` | 完成充值 |
| GET | `/api/user/search` | `SearchUsers` | 搜索用户 |
| GET | `/api/user/:id/oauth/bindings` | `GetUserOAuthBindingsByAdmin` | 用户 OAuth 绑定 |
| DELETE | `/api/user/:id/oauth/bindings/:provider_id` | `UnbindCustomOAuthByAdmin` | 解绑用户 OAuth |
| DELETE | `/api/user/:id/bindings/:binding_type` | `AdminClearUserBinding` | 清除用户绑定 |
| GET | `/api/user/:id` | `GetUser` | 获取用户 |
| POST | `/api/user/` | `CreateUser` | 创建用户 |
| POST | `/api/user/manage` | `ManageUser` | 管理用户（quota/status） |
| PUT | `/api/user/` | `UpdateUser` | 更新用户 |
| DELETE | `/api/user/:id` | `DeleteUser` | 删除用户 |
| DELETE | `/api/user/:id/reset_passkey` | `AdminResetPasskey` | 重置 Passkey |
| GET | `/api/user/2fa/stats` | `Admin2FAStats` | 2FA 统计 |
| DELETE | `/api/user/:id/2fa` | `AdminDisable2FA` | 管理员禁用 2FA |

#### 15.3.10 令牌管理（UserAuth）

| Method | Path | Controller | 用途 |
|--------|------|------------|------|
| GET | `/api/token/` | `GetAllTokens` | 令牌列表 |
| GET | `/api/token/search` | `SearchTokens` | 搜索令牌 |
| GET | `/api/token/:id` | `GetToken` | 单个令牌 |
| POST | `/api/token/:id/key` | `GetTokenKey` | 获取令牌密钥 |
| POST | `/api/token/` | `AddToken` | 创建令牌 |
| PUT | `/api/token/` | `UpdateToken` | 更新令牌 |
| DELETE | `/api/token/:id` | `DeleteToken` | 删除令牌 |
| POST | `/api/token/batch` | `DeleteTokenBatch` | 批量删除 |
| POST | `/api/token/batch/keys` | `GetTokenKeysBatch` | 批量获取密钥 |

#### 15.3.11 渠道管理（AdminAuth）

| Method | Path | Auth | Controller | 用途 |
|--------|------|------|------------|------|
| GET | `/api/channel/` | AdminAuth | `GetAllChannels` | 渠道列表 |
| GET | `/api/channel/search` | AdminAuth | `SearchChannels` | 搜索 |
| GET | `/api/channel/models` | AdminAuth | `ChannelListModels` | 模型列表 |
| GET | `/api/channel/models_enabled` | AdminAuth | `EnabledListModels` | 已启用模型 |
| GET | `/api/channel/ops` | AdminAuth | `GetChannelOps` | 操作信息 |
| GET | `/api/channel/:id` | AdminAuth | `GetChannel` | 单个渠道 |
| POST | `/api/channel/:id/key` | RootAuth | `GetChannelKey` | 渠道密钥（敏感，+ SecureVerificationRequired） |
| GET | `/api/channel/test` | AdminAuth | `TestAllChannels` | 测试全部 |
| GET | `/api/channel/test/:id` | AdminAuth | `TestChannel` | 测试单个 |
| GET | `/api/channel/update_balance` | AdminAuth | `UpdateAllChannelsBalance` | 更新全部余额 |
| GET | `/api/channel/update_balance/:id` | AdminAuth | `UpdateChannelBalance` | 更新单个余额 |
| POST | `/api/channel/` | AdminAuth | `AddChannel` | 添加 |
| PUT | `/api/channel/` | AdminAuth | `UpdateChannel` | 更新 |
| POST | `/api/channel/status/batch` | AdminAuth | `BatchUpdateChannelStatus` | 批量改状态 |
| POST | `/api/channel/:id/status` | AdminAuth | `UpdateChannelStatus` | 单个改状态 |
| DELETE | `/api/channel/disabled` | AdminAuth | `DeleteDisabledChannel` | 清理禁用 |
| POST | `/api/channel/tag/disabled` | AdminAuth | `DisableTagChannels` | 按 tag 禁用 |
| POST | `/api/channel/tag/enabled` | AdminAuth | `EnableTagChannels` | 按 tag 启用 |
| PUT | `/api/channel/tag` | AdminAuth | `EditTagChannels` | 编辑 tag |
| DELETE | `/api/channel/:id` | AdminAuth | `DeleteChannel` | 删除 |
| POST | `/api/channel/batch` | AdminAuth | `DeleteChannelBatch` | 批量删除 |
| POST | `/api/channel/fix` | AdminAuth | `FixChannelsAbilities` | 修复能力 |
| GET | `/api/channel/fetch_models/:id` | AdminAuth | `FetchUpstreamModels` | 拉取上游模型 |
| POST | `/api/channel/fetch_models` | AdminAuth | `FetchModels` | 批量拉取 |
| POST | `/api/channel/:id/codex/refresh` | AdminAuth | `RefreshCodexChannelCredential` | Codex 凭证刷新 |
| GET | `/api/channel/:id/codex/usage` | AdminAuth | `GetCodexChannelUsage` | Codex 用量 |
| GET | `/api/channel/:id/codex/usage/reset-credits` | AdminAuth | `GetCodexChannelRateLimitResetCredits` | Codex 限流重置 |
| POST | `/api/channel/:id/codex/usage/reset` | AdminAuth | `ResetCodexChannelUsage` | Codex 重置 |
| POST | `/api/channel/ollama/pull` | AdminAuth | `OllamaPullModel` | Ollama 拉模型 |
| POST | `/api/channel/ollama/pull/stream` | AdminAuth | `OllamaPullModelStream` | 流式拉模型 |
| DELETE | `/api/channel/ollama/delete` | AdminAuth | `OllamaDeleteModel` | Ollama 删模型 |
| GET | `/api/channel/ollama/version/:id` | AdminAuth | `OllamaVersion` | Ollama 版本 |
| POST | `/api/channel/batch/tag` | AdminAuth | `BatchSetChannelTag` | 批量设 tag |
| GET | `/api/channel/tag/models` | AdminAuth | `GetTagModels` | 按 tag 查模型 |
| POST | `/api/channel/copy/:id` | AdminAuth | `CopyChannel` | 复制渠道 |
| POST | `/api/channel/multi_key/manage` | AdminAuth | `ManageMultiKeys` | 多 Key 管理 |
| POST | `/api/channel/upstream_updates/apply` | AdminAuth | `ApplyChannelUpstreamModelUpdates` | 应用上游更新 |
| POST | `/api/channel/upstream_updates/apply_all` | AdminAuth | `ApplyAllChannelUpstreamModelUpdates` | 应用全部上游更新 |
| POST | `/api/channel/upstream_updates/detect` | AdminAuth | `DetectChannelUpstreamModelUpdates` | 检测上游变更 |
| POST | `/api/channel/upstream_updates/detect_all` | AdminAuth | `DetectAllChannelUpstreamModelUpdates` | 检测全部上游变更 |

#### 15.3.12 订阅

用户侧（UserAuth）：

| Method | Path | Controller | 用途 |
|--------|------|------------|------|
| GET | `/api/subscription/plans` | `GetSubscriptionPlans` | 可订阅计划 |
| GET | `/api/subscription/self` | `GetSubscriptionSelf` | 我的订阅 |
| PUT | `/api/subscription/self/preference` | `UpdateSubscriptionPreference` | 更新订阅偏好 |
| POST | `/api/subscription/balance/pay` | `SubscriptionRequestBalancePay` | 余额支付 |
| POST | `/api/subscription/epay/pay` | `SubscriptionRequestEpay` | 易支付 |
| POST | `/api/subscription/stripe/pay` | `SubscriptionRequestStripePay` | Stripe |
| POST | `/api/subscription/creem/pay` | `SubscriptionRequestCreemPay` | Creem |

订阅回调（public）：

| Method | Path | Controller |
|--------|------|------------|
| POST/GET | `/api/subscription/epay/notify` | `SubscriptionEpayNotify` |
| POST/GET | `/api/subscription/epay/return` | `SubscriptionEpayReturn` |

管理员（AdminAuth）：`/api/subscription/admin/plans`（CRUD + 状态）、`/api/subscription/admin/bind`、`/api/subscription/admin/plans/:id/subscriptions/reset`、`/api/subscription/admin/users/:id/subscriptions`（CRUD）、`/api/subscription/admin/user_subscriptions/:id/invalidate`、`/api/subscription/admin/user_subscriptions/:id`（delete）。

#### 15.3.13 系统选项 / 设置（RootAuth）

| Method | Path | Controller | 用途 |
|--------|------|------------|------|
| GET | `/api/option/` | `GetOptions` | 系统选项 |
| PUT | `/api/option/` | `UpdateOption` | 更新选项 |
| POST | `/api/option/payment_compliance` | `ConfirmPaymentCompliance` | 支付合规确认 |
| GET | `/api/option/channel_affinity_cache` | `GetChannelAffinityCacheStats` | 渠道亲和缓存统计 |
| DELETE | `/api/option/channel_affinity_cache` | `ClearChannelAffinityCache` | 清理缓存 |
| POST | `/api/option/rest_model_ratio` | `ResetModelRatio` | 重置模型倍率 |

#### 15.3.14 自定义 OAuth Provider（RootAuth）

`/api/custom-oauth-provider/`（CRUD） + `POST /api/custom-oauth-provider/discovery`（OIDC 发现）。

#### 15.3.15 性能管理（RootAuth）

| Method | Path | Controller |
|--------|------|------------|
| GET | `/api/performance/stats` | `GetPerformanceStats` |
| DELETE | `/api/performance/disk_cache` | `ClearDiskCache` |
| POST | `/api/performance/reset_stats` | `ResetPerformanceStats` |
| POST | `/api/performance/gc` | `ForceGC` |
| GET | `/api/performance/logs` | `GetLogFiles` |
| DELETE | `/api/performance/logs` | `CleanupLogFiles` |

#### 15.3.16 倍率同步（RootAuth）

| Method | Path | Controller |
|--------|------|------------|
| GET | `/api/ratio_sync/channels` | `GetSyncableChannels` |
| POST | `/api/ratio_sync/fetch` | `FetchUpstreamRatios` |

#### 15.3.17 兑换码（AdminAuth）

`/api/redemption/`（CRUD、搜索、批量删除无效）。

#### 15.3.18 日志

| Method | Path | Auth | Controller |
|--------|------|------|------------|
| GET | `/api/log/` | AdminAuth | `GetAllLogs` |
| GET | `/api/log/stat` | AdminAuth | `GetLogsStat` |
| GET | `/api/log/self/stat` | UserAuth | `GetLogsSelfStat` |
| GET | `/api/log/channel_affinity_usage_cache` | AdminAuth | `GetChannelAffinityUsageCacheStats` |
| GET | `/api/log/search` | AdminAuth | `SearchAllLogs` |
| GET | `/api/log/self` | UserAuth | `GetUserLogs` |
| GET | `/api/log/self/search` | UserAuth | `SearchUserLogs` |
| GET | `/api/log/token` | TokenAuthReadOnly | `GetLogByKey` |

#### 15.3.19 系统任务 / 实例（RootAuth）

`/api/system-task/log-cleanup`、`/api/system-task/list`、`/api/system-task/current`、`/api/system-task/:id`；
`/api/system-info/instances`、`DELETE /api/system-info/stale-instances`、`DELETE /api/system-info/instances/:node_name`。

#### 15.3.20 额度 / 用量数据

| Method | Path | Auth | Controller |
|--------|------|------|------------|
| GET | `/api/data/` | AdminAuth | `GetAllQuotaDates` |
| GET | `/api/data/users` | AdminAuth | `GetQuotaDatesByUser` |
| GET | `/api/data/self` | UserAuth | `GetUserQuotaDates` |
| GET | `/api/data/flow` | AdminAuth | `GetAllFlowQuotaDates` |
| GET | `/api/data/flow/self` | UserAuth | `GetUserFlowQuotaDates` |

#### 15.3.21 分组 / 预填

`GET /api/group/`（AdminAuth）、`/api/prefill_group/`（CRUD + Delete，AdminAuth）。

#### 15.3.22 任务查询（MJ / Suno/视频）

| Method | Path | Auth | Controller |
|--------|------|------|------------|
| GET | `/api/mj/self` | UserAuth | `GetUserMidjourney` |
| GET | `/api/mj/` | AdminAuth | `GetAllMidjourney` |
| GET | `/api/task/self` | UserAuth | `GetUserTask` |
| GET | `/api/task/` | AdminAuth | `GetAllTask` |

#### 15.3.23 供应商 / 模型元数据（AdminAuth）

- `/api/vendors/`（CRUD + 搜索）
- `/api/models/`（CRUD + 搜索 + `/api/models/missing` + `/api/models/sync_upstream/preview` + `POST /api/models/sync_upstream`）

#### 15.3.24 部署（Deployments，AdminAuth）

`/api/deployments/settings` + `test-connection`；`/api/deployments/`（CRUD + 容器/日志）+ `hardware-types` / `locations` / `available-replicas` / `price-estimation` / `check-name` + `/:id/extend`。

> 部署能力由 `pkg/ionet` 提供，对接外部 GPU/容器服务（参考 `docs/ionet-client.md`）。

### 15.4 关键 WebSocket / Streaming 端点

- `/v1/realtime` — OpenAI Realtime（双向 WS）
- `/v1/messages?stream=true` — Claude 流式 SSE
- `/v1/chat/completions?stream=true` — OpenAI 流式 SSE
- `/v1/responses?stream=true` — Responses 流式

### 15.5 前端静态托管

`router/web-router.go` 通过 `embed.FS` 内置 `web/dist`，所有非 API/非资产路径回退到 SPA `index.html`。支持 `FRONTEND_BASE_URL` 前后端分离部署。

### 15.6 关键路由文件索引

| 文件 | 职责 |
|------|------|
| `router/main.go` | 路由总装 |
| `router/api-router.go` | `/api` 主路由树 |
| `router/relay-router.go` | AI relay（`/v1`、`/mj`、`/suno`、`/v1beta`） |
| `router/video-router.go` | 视频 relay 路由 |
| `router/dashboard.go` | 旧版 dashboard billing |
| `router/web-router.go` | 静态前端托管 |

---

## 附 A：术语表

| 术语 | 含义 |
|------|------|
| Channel | 上游 API 提供商的一条配置（Key + URL + 模型 + 分组） |
| Group | 用户分组，决定用户能用哪些模型 |
| Token | 客户端调用 AI 接口的访问令牌（不是 OAuth Token） |
| Quota | 抽象计费单位，1 美元 = `common.QuotaPerUnit`（默认 500000）quota |
| Affinity | 渠道粘性，同一会话优先同一上游 |
| Task | 异步任务（Midjourney / Suno / Kling / Jimeng 等） |
| DTO | Data Transfer Object，请求/响应结构体 |
| Relay | New API 内部的 AI 代理层 |

## 附 B：关键源码索引

| 关注点 | 入口 |
|--------|------|
| 启动 | `main.go` |
| 路由 | `router/main.go` |
| 中间件 | `middleware/` |
| 渠道适配 | `relay/relay_adaptor.go`、`relay/channel/*/adapter.go` |
| 协议 handler | `relay/audio_handler.go`、`chat_completions_via_responses.go`、`claude_handler.go`、`gemini_handler.go`、`embedding_handler.go`、`image_handler.go`、`rerank_handler.go`、`responses_handler.go`、`mjproxy_handler.go` |
| 任务 | `relay/relay_task.go`、`relay/channel/task/*`、`service/task*.go` |
| 计费 | `service/billing.go`、`relay/helper/price.go`、`setting/ratio_setting/` |
| 限流 | `middleware/rate-limit.go`、`model-rate-limit.go` |
| 缓存 | `model/channel_cache.go`、`pkg/cachex/` |
| 支付 | `controller/topup*.go`、`controller/subscription_payment_*.go`、`service/epay.go` |
| 审计 | `model/log.go` |
| 性能 | `controller/performance.go`、`setting/performance_setting/` |
| 国际化 | `i18n/`（后端）、`web/src/i18n/`（前端） |

---

> 本文档由源码静态扫描自动汇总，所有能力均对应可定位的源码文件 / 接口定义；后续可结合 `openspec/specs/` 把每条能力沉淀为正式 spec。
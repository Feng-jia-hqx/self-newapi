# newapi 计费异常排查 Runbook

> 团队运维 / 客服 / 对账 应急手册
> 配套阅读：`docs/BILLING_MODEL.md`、`PRODUCT_CAPABILITIES.md` §7
> 适用版本：newapi 主干

---

## 目录

1. [排障总思路](#1-排障总思路)
2. [场景 1：扣费比预期多](#2-场景-1扣费比预期多)
3. [场景 2：扣费比预期少](#3-场景-2扣费比预期少)
4. [场景 3：模型广场展示价 ≠ 实际扣费](#4-场景-3模型广场展示价--实际扣费)
5. [场景 4：用户反馈"没调用也扣费了"](#5-场景-4用户反馈没调用也扣费了)
6. [场景 5：同模型多渠道，价格贵的优先用了](#6-场景-5同模型多渠道价格贵的优先用了)
7. [场景 6：quota 出现负数或异常巨大值](#7-场景-6quota-出现负数或异常巨大值)
8. [场景 7：group_ratio 修改后没生效](#8-场景-7group_ratio-修改后没生效)
9. [场景 8：充值到账但扣费还是失败](#9-场景-8充值到账但扣费还是失败)
10. [场景 9：缓存 / 图像 / 音频计费异常](#10-场景-9缓存--图像--音频计费异常)
11. [场景 10：Codex（ChatGPT 订阅）渠道的扣费看不懂](#11-场景-10codexchatgpt-订阅渠道的扣费看不懂)
12. [通用排查工具](#12-通用排查工具)

---

## 1. 排障总思路

**永远按以下顺序排查，不要跳步：**

```
① 查 log 表拿到请求快照
       ↓
② 解读快照里的关键字段（model_ratio / group_ratio / completion_ratio / quota_type）
       ↓
③ 用 BILLING_MODEL.md 的公式手算一遍，对照实际 quota
       ↓
④ 差异点 = 故障点
       ↓
⑤ 按对应场景处理
```

### 第一步：拿到请求快照

排查任何计费问题前，**必须先定位到具体的某次请求**。

```sql
-- 管理员视角
-- 注意：logs 表的列只有下面这些（model/log.go）。
-- 倍率/缓存/图像/音频等明细都存在 `other` 字段的 JSON 里，不是表列！
SELECT id, user_id, token_id, channel_id, model_name,
       prompt_tokens, completion_tokens,
       quota, content, `group`, is_stream, request_id, created_at,
       other
FROM logs
WHERE id = ? OR created_at BETWEEN ? AND ?
ORDER BY id DESC LIMIT 50;
```

> `logs` 表的列（`model/log.go:19-40`）：`id / user_id / created_at / type / content / username / token_name / model_name / quota(int) / prompt_tokens / completion_tokens / use_time / is_stream / channel_id / token_id / group / ip / request_id / other`。
>
> `created_at` 是 Unix 秒级时间戳（`int64`），**不是** `created_time`。
>
> `quota` 是请求结算后的快照值，**改 ratio 不会回溯**。

### 解读 `other` JSON（明细倍率都在这里）

`other` 是一个 JSON 字符串（`service/log_info_generate.go` 的 `GenerateTextOtherInfo` / `GenerateClaudeOtherInfo` / `GenerateAudioOtherInfo` 写入）。查某个明细要用 `JSON_EXTRACT`：

```sql
SELECT
  JSON_EXTRACT(other, '$.model_ratio')        AS model_ratio,
  JSON_EXTRACT(other, '$.group_ratio')        AS group_ratio,
  JSON_EXTRACT(other, '$.user_group_ratio')   AS user_group_ratio,   -- group_group_ratio 命中时写入
  JSON_EXTRACT(other, '$.completion_ratio')   AS completion_ratio,
  JSON_EXTRACT(other, '$.cache_ratio')        AS cache_ratio,
  JSON_EXTRACT(other, '$.cache_tokens')       AS cache_tokens,
  JSON_EXTRACT(other, '$.model_price')        AS model_price,
  JSON_EXTRACT(other, '$.cache_creation_tokens')     AS cache_creation_tokens,
  JSON_EXTRACT(other, '$.cache_creation_ratio')      AS cache_creation_ratio,
  JSON_EXTRACT(other, '$.cache_creation_tokens_1h')  AS cache_creation_tokens_1h,
  JSON_EXTRACT(other, '$.image_ratio')        AS image_ratio,
  JSON_EXTRACT(other, '$.image_output')       AS image_tokens,
  JSON_EXTRACT(other, '$.audio_ratio')        AS audio_ratio,
  JSON_EXTRACT(other, '$.audio_completion_ratio') AS audio_completion_ratio,
  JSON_EXTRACT(other, '$.audio_input')        AS audio_in_tokens,
  JSON_EXTRACT(other, '$.audio_output')       AS audio_out_tokens,
  quota
FROM logs
WHERE id = ?;
```

> ⚠️ 不要把这些当**表列**直接 `SELECT cache_tokens ...`，会报 `unknown column`。也没有 `use_price` / `tool_call_surcharge_quota` / `group_group_ratio` / `quota_saturation` 这些 key —— 它们不存在。`group_group_ratio` 的覆盖值实际 key 是 `user_group_ratio`（仅命中时写入）。

### 关键字段解读

| 字段 | 含义 | 来源 |
|------|------|------|
| `other.model_ratio` | 该次请求的模型基础倍率 | `setting/ratio_setting/model_ratio.go` |
| `other.group_ratio` | 用户所在分组的倍率 | `setting/ratio_setting/group_ratio.go` |
| `other.user_group_ratio` | group_group_ratio 命中时的覆盖值（仅命中时存在） | 同上 |
| `other.completion_ratio` | 输出 token 倍率 | `setting/ratio_setting/model_ratio.go` |
| `other.cache_ratio` | 缓存命中倍率 | `setting/ratio_setting/cache_ratio.go` |
| `quota_type` | 是否固定价（1=固定价，0=按 token） | `model/pricing.go:298-303`（从 `use_price` 派生） |
| `other.model_price` | 固定价（quota_type=1 时） | 同上 |

---

## 2. 场景 1：扣费比预期多

### 2.1 检查清单

| 检查项 | 如何查 | 常见原因 |
|--------|--------|----------|
| `completion_tokens` 是否异常大 | `logs.completion_tokens` | 输出 token 激增（推理模型长 CoT） |
| 是否触发了缓存写入 | `JSON_EXTRACT(other,'$.cache_creation_tokens')` | Anthropic prompt caching 创建计费 |
| 是否有 web_search / file_search / 图像调用 | `other` 里的 `web_search`、`image_generation_call` 等 key | 工具调用按次独立计费 |
| `group_ratio` 是否被覆盖 | `JSON_EXTRACT(other,'$.user_group_ratio')` 是否存在 | 启用了 group_group_ratio 交叉定价 |
| `model_ratio` 是否近期被改过 | 审计系统设置 → 模型倍率变更 | 运营提价 |
| 用户是否临时落到特殊 group | 用户详情 → 分组 | 测试 / 试用 group |

### 2.2 推理模型（CoT）长输出扣费暴涨

**现象**：调用一次 DeepSeek-R1 / o3-mini / Claude thinking，单次扣费是普通模型的 5-10 倍。

**根因**：`completion_tokens` 包含思维链 token，按正常 `completion_ratio` 计费。

**处理**：
1. 让用户确认是否启用了"思考模式"（thinking / reasoning_effort）
2. 如不愿为 CoT 付费，可关闭 thinking 或换模型
3. 退款依据：明确告知 CoT 是正常计费项，不退

**源码定位**：输出计费在 OpenAI 路径 `relay/compatible_handler.go:382-384`（`completion_tokens × completion_ratio`，并入 `× ratio`）；Claude 路径 `service/quota.go:285-286`。

### 2.3 缓存写入扣费

**现象**：用户首次调用扣费正常，**第二次开始**反而更贵。

**根因**：首次调用创建了 prompt cache（写入计费），第二次起才是缓存命中（折扣）。

**处理**：
1. 查看 `cache_creation_tokens` 与 `cache_tokens` 的差值（Claude 路径还分 5m / 1h，见 `other.cache_creation_tokens_5m` / `_1h`）
2. 缓存写入倍率：5m 默认 ≈ 1.25；1h = 5m 基准 × (6/3.75) ≈ 2.0（常量 `relay/helper/price.go:17`）
3. 解释给用户：长期重复调用同一 prompt 才会摊薄

**源码定位**：5m / 1h 分档累加在 `service/quota.go:279-280`（Claude 路径 `PostClaudeConsumeQuota`）；OpenAI 路径用单一 `cache_create_ratio`（`relay/compatible_handler.go:358`）。

### 2.4 工具调用额外计费

**现象**：开启 web_search / file_search / 图像生成等内置工具后扣费比纯文本贵。

**根因**：这些工具在常规 token 计费之外，按"每千次调用价格"独立累加。

**处理**：
1. 在 `other` 里查 `web_search_call_count` / `web_search_price`、`image_generation_call` 等 key
2. 如确实调用了工具，是合理计费

**源码定位**：`relay/compatible_handler.go:278-334`、`:393-398`（各自独立 `Add` 进 `quotaCalculateDecimal`）。

---

## 3. 场景 2：扣费比预期少

### 3.1 检查清单

| 检查项 | 排查路径 | 常见原因 |
|--------|----------|----------|
| 是否走了缓存命中 | `JSON_EXTRACT(other,'$.cache_tokens')` | 命中后按 `cache_ratio`（如 0.1）折扣 |
| 是否启用了 `group_group_ratio` 覆盖 | `JSON_EXTRACT(other,'$.user_group_ratio')` | 用户组 × 渠道组有特殊折扣 |
| 是否误判为固定价 | `quota_type` 是否 = 1 | 模型被识别为固定价模型 |
| 用户余额被锁定（并发） | 用户 quota 历史 | pre-consume 后未 settle |

### 3.2 缓存命中导致"看着便宜"

**处理**：
1. 给用户解释：缓存命中 = `cache_ratio`（如 claude 0.1）折扣后价格
2. 这是**预期行为**，不是 bug

### 3.3 余额与扣费对不上

**现象**：用户反馈"扣了 X，但我看到账单是 Y"。

**根因**：newapi 采用 **预扣 + 结算**模式：
```
请求进入 → 估算可能扣费 → PreConsume（先扣）→ 实际响应 → Settle（补差或部分退还）
```

**处理**：
1. 用户实际 quota 变化 = 预扣 − 退款（settle）
2. `logs.quota` 是"结算后"值
3. 短时间内的"扣了又退"是正常的并发保护机制

**源码定位**：预扣 `relay/helper/price.go:90-91`（`ModelPriceHelper` 算 `preConsumedQuota`）；结算 `service.SettleBilling`（在 `relay/compatible_handler.go:429`、`service/quota.go:313` 调用）。

---

## 4. 场景 3：模型广场展示价 ≠ 实际扣费

### 4.1 诊断步骤

1. 用户登录后访问 `模型广场`，记下看到的 gpt-4o 显示价 = **A**
2. 用户调用 gpt-4o 后查 log，结算 quota 转成显示币种 = **B**
3. 若 A ≠ B，按下表诊断

| 差异原因 | A 的来源 | B 的来源 | 修复方法 |
|----------|---------|---------|----------|
| 启用了 `group_group_ratio`（仅影响未登录访客） | 未登录访客的展示不含这层覆盖 | 后端扣费始终读 `GetGroupGroupRatio` | 登录用户展示已合并该值（`controller/pricing.go:24-29`），应一致；仅未登录访客有差异 |
| 用户筛选的分组 ≠ 实际分组 | 前端按筛选分组算 | 后端按 token/用户实际分组算 | 让用户筛选自己所在分组 |
| 用户是未登录 / 默认 `all` 视图 | 前端取模型可用分组中 `group_ratio` 最小值（销售最优价） | 后端按用户真实分组算 | 默认 UX，非 bug |
| 展示币种 ≠ 后端 quota 单位 | 前端按 `priceRate` / `usd_exchange_rate` 换算 | 后端纯 quota（整数） | 统一对照 `common.QuotaPerUnit`（默认 500000） |
| `× 2` 展示系数 | 前端硬编码 `model_ratio × 2 × group_ratio`（每 1M token） | 后端按 quota 单位换算 | `×2` 仅在 `QuotaPerUnit=500000` 时对齐；改过该值会脱钩 |
| `model_ratio` 1 分钟缓存 | `/api/pricing` 走 `model.GetPricing()` 的 TTL 缓存 | 改 ratio 后最多 1 分钟才反映 | 等 1 分钟后刷新 |
| 缓存/图像/音频细分倍率 | 前端只展示 input/output/cache 等主项 | 后端逐项累加 | 比对 `other` 里各项细分倍率 |

### 4.2 速算验证（SQL）

```sql
-- 反推本次请求实际用的 model_ratio / group_ratio
SELECT
  model_name,
  JSON_EXTRACT(other, '$.model_ratio')                       AS model_ratio,
  JSON_EXTRACT(other, '$.group_ratio')                       AS group_ratio,
  JSON_EXTRACT(other, '$.user_group_ratio')                  AS user_group_ratio,  -- 若非 NULL 说明触发了覆盖
  quota, prompt_tokens, completion_tokens
FROM logs
WHERE model_name = 'gpt-4o'
ORDER BY id DESC LIMIT 10;
```

如果 `user_group_ratio` 不为 NULL，说明该请求触发了 `group_group_ratio` 覆盖。

---

## 5. 场景 4：用户反馈"没调用也扣费了"

### 5.1 常见原因

| 现象 | 真实原因 | 处理 |
|------|----------|------|
| 用户说"我没调 API"但 quota 减少 | 1) pre-consume 后调用失败未退款<br>2) 异步任务（MJ/Suno/视频）扣费<br>3) Token 被他人盗用<br>4) 用户误操作调了 Playground `/pg/chat/completions` | 看 `logs.channel_id` / `logs.token_id` / `logs.created_at`，定位真实调用方 |
| 用户看到自己 quota 减少但 log 表无记录 | 1) pre-consume 的 quota 还"挂"在 in-flight 请求上<br>2) 异步任务尚未 settle | 查任务进度表，等待结算完成 |

### 5.2 异步任务扣费（MJ / Suno / 视频）

**特别提醒**：异步任务的 quota 扣费时点 ≠ 提交时点。

```
提交任务  →  pre-consume（先扣一笔）
       ↓
任务排队
       ↓
任务完成  →  按真实 usage settle（可能补扣或部分退）
       ↓
任务失败  →  按失败类型 settle（部分退或不退）
```

**处理**：
1. 查任务进度表，看任务 `status` 和 `quota`
2. 失败任务是否退款取决于平台（Kling 通常退，豆包视频可能不退）
3. 与用户沟通时区分"提交时扣"和"完成时扣"

---

## 6. 场景 5：同模型多渠道，价格贵的优先用了

### 6.1 根因确认

newapi 渠道选择**完全不感知渠道成本**——只按 `priority` + `weight` 加权随机。

**源码定位**：`model/channel_cache.go` 的 `GetRandomSatisfiedChannel`（约 96-191 行）。

```go
// 纯 priority + weight 选择，无 cost_ratio
// Channel 模型（model/channel.go）只有 Weight(*uint)、Priority(*int64)，没有成本字段
```

### 6.2 用户反馈"贵渠道优先"

**处理**：
1. 解释：**newapi 没有按渠道成本自动选最便宜的功能**
2. 临时方案：把便宜渠道的 `priority` 调高、`weight` 调大
3. 长期方案：见 §6.4 二次开发

### 6.3 配置步骤（手动让便宜渠道优先）

```
管理后台 → 渠道管理 → 编辑（便宜的渠道）
  - 优先级 priority: 调到 10（高于其他）
  - 权重 weight: 调到 100（更高概率被选中）
```

### 6.4 完整方案：成本感知渠道路由（需二次开发）

如需自动按渠道成本选择，需修改：

| 改动点 | 位置 |
|--------|------|
| 1. `Channel` 模型加 `cost_ratio` 字段 | `model/channel.go` |
| 2. 渠道编辑表单加 cost_ratio 输入 | `controller/channel.go` `AddChannel` / `UpdateChannel` |
| 3. 数据库迁移（3 个方言兼容） | `model/main.go` 的迁移机制 |
| 4. `GetRandomSatisfiedChannel` 按 cost_ratio 升序、同 cost_ratio 内按 weight 加权 | `model/channel_cache.go` |
| 5. 管理后台展示渠道 cost_ratio | `web/src/pages/Channel/EditChannel.js` |

工作量大；可作为 OpenSpec 提案沉淀。

---

## 7. 场景 6：quota 出现负数或异常巨大值

### 7.1 这是严重问题，需立即处理

负数 quota = 退过头的迹象。巨大 quota = 可能有溢出或缺失边界检查。

### 7.2 排查清单

| 检查项 | 排查命令/路径 | 修复方案 |
|--------|--------------|----------|
| `logs.quota < 0` | `SELECT * FROM logs WHERE quota < 0` | 检查上游返回 usage 是否异常；正常情况下 `model_ratio≠0 且计算结果≤0` 时会被内联置为 1 |
| `users.quota < 0` | `SELECT * FROM users WHERE quota < 0` | 手动调整；排查是否有重复退款 |
| `users.quota` 单次跳变巨大 | `SELECT * FROM data_updates WHERE ...` | 排查上游 deduction 是否异常 |
| 同请求 quota 远超 token 数 × 倍率 | 比较 `prompt_tokens + completion_tokens` 与 quota | 可能是 max_tokens 未校验或上游 usage 异常 |

### 7.3 配额最小值保护机制（实际实现）

> ⚠️ 注意：代码中**不存在** `common/quota_math.go`、`QuotaClamp`、`attachQuotaSaturation`、`log.other.admin_info.quota_saturation` 这些（早期文档误记）。实际的保护是**内联逻辑**：

- OpenAI 路径：`relay/compatible_handler.go:386-388` —— `ratio` 非零但 `quotaCalculateDecimal ≤ 0` 时置为 1。
- Claude 路径：`service/quota.go:291-293` —— `modelRatio != 0 && calculateQuota <= 0` 时置为 1。
- 音频路径：`service/quota.go:82-84`（`calculateAudioQuota` 内）同样的最小值保护。
- `log.other.admin_info` 实际只记录 `use_channel`、`is_multi_key`、`multi_key_index`、`local_count_tokens`、channel_affinity 等（`service/log_info_generate.go:58-73`），**没有饱和审计事件**。

**如果发现 quota 异常**：上述保护只能挡住"计算结果为 0/负"的情况，挡不住"上游 usage 本身异常巨大"。需结合上游返回排查。

### 7.4 立刻止血

```sql
-- 临时冻结异常账号
UPDATE users SET status = 2 WHERE id = ?;

-- 回滚异常 quota 调整（需人工核对每条）
-- 推荐做法：在管理后台对该用户做手动额度调整，系统会记一笔 manage 类 log
```

> `status`：1=enabled、2=disabled（`common/constants.go:186-189`）。

---

## 8. 场景 7：group_ratio 修改后没生效

### 8.1 排查清单

| 现象 | 排查方法 | 原因 |
|------|----------|------|
| 修改了但页面没刷新 | 浏览器硬刷（Ctrl+Shift+R） | 前端组件缓存 |
| 改完 `/api/pricing` 返回旧 group_ratio | 调 `setting/ratio_setting/group_ratio.go:UpdateGroupRatioByJSONString` 看是否报错 | 调用失败看错误码；成功则立即生效 |
| 用户实际扣费还是旧的 | 查最新 log 的 `other.group_ratio` | 若旧值，确认用户实际 group |
| 部分用户看到新值，部分还是旧 | 用户分组不匹配 | `group_ratio` 按用户所在 group 取，确认用户实际 group |
| 改的是 model_ratio 不是 group_ratio | model_ratio 走 `model.GetPricing()` 的 1 分钟 TTL 缓存 | **最多等 1 分钟**才反映（见场景 3） |

### 8.2 配置接口

`setting/ratio_setting/group_ratio.go:UpdateGroupRatioByJSONString(jsonStr)` 接收 JSON 字符串，直接覆盖内存 `RWMap`。

调用入口：管理后台 `系统设置 → 倍率设置 → 分组倍率` 编辑表单 → 保存。

### 8.3 生效时机

- **`group_ratio` 修改后立即生效**，无缓存、无延迟（内存 `RWMap`，`controller/pricing.go` 每次请求实时 `GetGroupRatioCopy()`）。
- **`model_ratio` 修改有最多 1 分钟延迟**（`model/pricing.go:63-75` 的 TTL 缓存）。
- 前端 React 组件可能在内存中保持旧值，**需硬刷浏览器**。

---

## 9. 场景 8：充值到账但扣费还是失败

### 9.1 区分几种"失败"

| 报错 | 真实原因 | 修复 |
|------|----------|------|
| `user quota is not enough` | 用户 quota < 本次预估扣费 | 让用户充值或确认充值到账 |
| `token quota is not enough` | token `remain_quota` 不足 | 检查 token 独立额度设置 |
| `token remain quota is not enough` (pre-consume) | 预扣时余额不够 | 同上 |
| 用户充值了但仍报 quota 不足 | 充值未回调成功 / 入错账户 | 查 `topups` 表和支付 Webhook 日志 |

### 9.2 充值未到账排查

```sql
-- 查该用户最近的充值记录
SELECT * FROM topups WHERE user_id = ? ORDER BY id DESC LIMIT 10;

-- 查充值类 log（type=1 是 topup）
SELECT * FROM logs WHERE type = 1 AND user_id = ? ORDER BY id DESC LIMIT 10;
```

> `logs.type`：0=unknown、1=topup、2=consume、3=manage、4=system、5=error、6=refund（`model/log.go:43-51`）。

### 9.3 充值回调失败常见原因

| 支付方式 | 常见失败 | 排查 |
|----------|----------|------|
| 易支付（epay） | 异步通知 URL 配置错误 | 管理后台 → 系统设置 → 支付设置 → 易支付 → 通知地址（`/api/user/epay/notify`） |
| Stripe | Webhook 签名验证失败 | 检查 Stripe Webhook Secret 配置；回调 `/api/stripe/webhook` |
| Creem | 回调 IP 白名单 / 网关放行 | 检查 nginx/网关是否放行 Creem IP；回调 `/api/creem/webhook` |

> newapi 实际支持的支付方式只有：**易支付（epay）、Stripe、Creem** + 兑换码 + 管理员手动充值（`controller/topup.go`、`controller/topup_stripe.go`、`controller/topup_creem.go`、`service/epay.go`、`controller/redemption.go`）。**不存在 Waffo / Pancake 等支付方式。**

---

## 10. 场景 9：缓存 / 图像 / 音频计费异常

### 10.1 缓存计费异常

| 现象 | 排查 |
|------|------|
| 缓存命中没打折 | 查 `other.cache_ratio` 是否设了（claude 默认 0.1） |
| 缓存写入反而更贵 | 正常，5m 写入倍率 ≈ 1.25；OpenAI 官方计价 |
| 1h 缓存写入很贵 | 正常，1h = 5m 基准 × (6/3.75) ≈ 2.0（仅 Claude 路径区分 5m/1h） |
| Claude 缓存写入没分成 5m / 1h | 看 `other.cache_creation_tokens_5m` 和 `other.cache_creation_tokens_1h` 是否都有值 |

### 10.2 图像计费异常

| 现象 | 排查 |
|------|------|
| 多张图扣费不对 | 固定价模型按"次 × model_price × group_ratio"；gpt-image-1 等按 token |
| 图像编辑比生成贵 | 正常，编辑需要额外算 input token |
| qwen-image / qwen-image-edit 调用方不对 | 走 `/v1/images/generations` 与 `/v1/images/edits` 路径要分清 |

### 10.3 音频计费异常

| 现象 | 排查 |
|------|------|
| 音频输入/输出 token 明细 | 看 `other.audio_input` / `other.audio_output` |
| TTS / 转录计费 | 走 `calculateAudioQuota`（`service/quota.go:50-87`），公式 = `text_in + text_out×completion_ratio + audio_in×audio_ratio + audio_out×audio_ratio×audio_completion_ratio`，再 `× model_ratio × group_ratio` |
| 音频输入和输出倍率反了 | 看 `other.audio_ratio` vs `other.audio_completion_ratio` 配置 |

---

## 11. 场景 10：Codex（ChatGPT 订阅）渠道的扣费看不懂

### 11.1 特殊性

Codex 渠道（`ChannelTypeCodex = 57`）对接 ChatGPT 订阅，计费语义与普通按 token 渠道不同，需结合实际渠道配置理解。它仅支持 `/v1/responses` 与 `/v1/responses/compact`（`relay/channel/codex/adaptor.go`）。

### 11.2 排查方式

```sql
-- 查 codex 相关调用记录
SELECT id, model_name, quota, other, created_at
FROM logs WHERE channel_id = ?
ORDER BY id DESC LIMIT 20;
```

### 11.3 常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| Codex 凭证刷新失败 | access_token 过期 | `POST /api/channel/:id/codex/refresh` |
| 用量/限流信息查不到 | 接口或凭证问题 | `GET /api/channel/:id/codex/usage` |

---

## 12. 通用排查工具

### 12.1 关键 SQL 速查

```sql
-- 某用户最近的扣费记录
SELECT id, model_name, prompt_tokens, completion_tokens, quota, created_at
FROM logs WHERE user_id = ? AND type = 2
ORDER BY id DESC LIMIT 50;

-- 某渠道最近的成功率
SELECT
  COUNT(*) AS total,
  SUM(CASE WHEN type = 2 THEN 1 ELSE 0 END) AS consume,
  SUM(quota) AS total_quota
FROM logs WHERE channel_id = ?
AND created_at > UNIX_TIMESTAMP(NOW() - INTERVAL 1 DAY);

-- 解析某条 log 的完整明细倍率
SELECT id, model_name, quota, other FROM logs WHERE id = ?;

-- 模型广场某个模型的所有调用记录
SELECT id, user_id, channel_id, quota,
       JSON_EXTRACT(other, '$.model_ratio') AS model_ratio,
       JSON_EXTRACT(other, '$.group_ratio') AS group_ratio
FROM logs WHERE model_name = 'gpt-4o'
ORDER BY id DESC LIMIT 100;
```

### 12.2 关键 API 速查

| 接口 | 用途 |
|------|------|
| `GET /api/log` | 管理员查所有 log |
| `GET /api/log/self` | 用户查自己的 log |
| `GET /api/log/stat` | 管理员统计 |
| `GET /api/pricing` | 查看当前 model_ratio / group_ratio 配置（含登录用户的 group_group_ratio 合并） |
| `GET /api/user/self` | 查看用户实际所在分组 |
| `GET /api/channel/:id/codex/usage` | Codex 渠道用量 |

### 12.3 关键环境变量速查

| 变量 | 作用 |
|------|------|
| `QUOTA_PER_UNIT` | 1 美元 = ? quota（默认 500000，`common/constants.go:22`） |
| `USD_EXCHANGE_RATE` | USD/CNY 换算（用于前端 CNY 展示） |
| `DEBUG=true` | 开启调试日志 |
| `REDIS_CONN_STRING` | 启用 Redis 用于分布式 quota 锁 |

### 12.4 关键源码文件速查

| 关注点 | 文件 |
|--------|------|
| OpenAI 路径计费 | `relay/compatible_handler.go`（约 336-408 行） |
| Claude 路径计费 | `service/quota.go`（`PostClaudeConsumeQuota`，275-289 行） |
| 音频 / Realtime 计费 | `service/quota.go`（`calculateAudioQuota`，50-87 行） |
| group_ratio 决定 + 预扣 | `relay/helper/price.go`（`HandleGroupRatio` / `ModelPriceHelper`） |
| 渠道选择（priority + weight） | `model/channel_cache.go`（`GetRandomSatisfiedChannel`） |
| 分发中间件 | `middleware/distributor.go` |
| `log.other` 明细生成 | `service/log_info_generate.go` |
| 模型定价 + 1 分钟缓存 | `model/pricing.go`、`controller/pricing.go` |
| 模型倍率 / 缓存倍率 / 分组倍率 | `setting/ratio_setting/` |

---

## 速记：4 个万能问句

排障时，先问这 4 个问题，90% 的 case 能找到方向：

1. **用的是哪个 group？** → 决定 `group_ratio`
2. **调的是哪个 model？** → 决定 `model_ratio` / `model_price`
3. **请求里 input / output / cache / image / audio 各多少？** → 决定各细项倍率
4. **是否启用了 GroupGroupRatio？** → 决定是否有额外覆盖

答完这 4 个问题，配合 log 表里的快照（注意倍率在 `other` JSON 里），对照 `BILLING_MODEL.md` 的公式一算，差异点就是故障点。

---

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-07-25 | 初版，配套 `docs/BILLING_MODEL.md` |
| 2026-07-27 | 按真实源码校正：所有 SQL 改用 `JSON_EXTRACT(other,...)`（明细倍率是 JSON key 不是表列）；删除虚构的 `service/text_quota.go`、`common/quota_math.go`、`QuotaClamp`、`attachQuotaSaturation`、`quota_saturation`、`tool_call_surcharge_quota`；源码定位改为 `relay/compatible_handler.go` / `service/quota.go` / `relay/helper/price.go`；修正 `created_at`、支付方式（无 Waffo/Pancake）、model_ratio 1 分钟缓存等错误 |

# newapi 计费与定价模型速查表

> 团队 wiki 速查文档 · 与 `PRODUCT_CAPABILITIES.md` §7 配套使用
> 适用版本：newapi 主干
> 目标读者：产品、运营、客服、对账、财务、集成方

---

## 一句话总览

```text
模型定价（model_ratio）= 模型广场上所有人看到的一致性基础价格
分组定价（group_ratio）= 每个分组对该基础价格的乘数
用户在模型广场看到的最终价 = 模型定价 × 分组定价
用户实际扣费 = 模型定价 × 分组定价（+ 各细项倍率 + GroupGroupRatio 可选覆盖）
```

---

## 三个定价层（管理后台路径）

newapi 的"计费与支付"页面下，所有定价都在这三个字段里完成：

| 字段 | 后台路径 | 数据结构 | 维度 | 一致性 |
|------|----------|----------|------|--------|
| `model_ratio` / `model_price` | 计费与支付 → **模型定价** | `map[model_name]float64` | 模型 | **全员一致**（同一份） |
| `group_ratio` | 计费与支付 → **分组定价** | `map[group_name]float64` | 分组 | **按用户所在分组取** |
| `group_group_ratio` | 计费与支付 → **分组对分组倍率** | `map[user_group][using_group]float64` | 二维矩阵 | **可选**；扣费时覆盖上面的 group_ratio |

> 数据结构见 `setting/ratio_setting/group_ratio.go`（`defaultGroupRatio` 默认 `default/vip/svip` 均 = 1；`defaultGroupGroupRatio` 默认 `{vip: {edit_this: 0.9}}` 为占位示例）。

---

## 价格链（一张图）

```
┌──────────────────────────────────────────────────────────────┐
│  管理员在 系统设置 → 计费与支付 配置                            │
│                                                              │
│  ① 模型定价 model_ratio      全员一致基础价                   │
│  ② 分组定价 group_ratio      按用户分组乘数                   │
│  ③ 分组对分组倍率 (可选)      用户组 × 渠道组 覆盖              │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
         ┌──────────────────────────────────┐
         │  所有用户从 /api/pricing 拿到     │
         │  同一份 model_ratio              │
         │  + 自己可见的 group_ratio map     │
         └──────────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
   ┌────────────────────┐  ┌────────────────────┐
   │ 前端 模型广场显示   │  │ 后端 API 实际扣费   │
   │                    │  │                    │
   │ display_price =    │  │ ratio =            │
   │  model_ratio ×     │  │  model_ratio ×     │
   │  group_ratio       │  │  group_ratio       │
   │  (×2 展示系数)     │  │  (× 各细项倍率)    │
   └────────────────────┘  └────────────────────┘
              │                       │
              └───────────┬───────────┘
                          ▼
            display_price ≈ 实际扣费
      （同一份配置；例外见下方坑 1 / 坑 2）
```

---

## 公式详解

### 前端展示（`web/src/helpers/utils.jsx` 的 `calculateModelPrice`，约 611–762 行）

```text
input  price = model_ratio × 2 × group_ratio
output price = input price × completion_ratio
cache  price = input price × cache_ratio
create price = input price × create_cache_ratio
image  price = input price × image_ratio
audio  price = input price × audio_ratio
audio  out  = input price × audio_ratio × audio_completion_ratio
```

固定价模型（`quota_type === 1`）：`price = model_price × group_ratio`（同函数 :742）。

> ⚠️ 关于 `× 2`：它是前端**硬编码常数**（`utils.jsx:652` 的 `record.model_ratio * 2 * usedGroupRatio`），**并不读取** `common.QuotaPerUnit`。它只在 `QuotaPerUnit = 500000`（默认值，`common/constants.go:22`）时与扣费侧恰好对齐 —— 因为每 1M token 的美元价 = `model_ratio × group_ratio × 1_000_000 / 500_000 = model_ratio × group_ratio × 2`。**若运维改了 `QuotaPerUnit`，扣费侧会跟着变，但前端这个 `× 2` 不会变，展示价与扣费价就会脱钩。** 这是历史惯例，非代码保证。

### 后端扣费

`group_ratio` 由 `relay/helper/price.go:20-46` 的 `HandleGroupRatio` 决定：若 `GetGroupGroupRatio(userGroup, usingGroup)` 命中则覆盖为该值，否则取 `GetGroupRatio(usingGroup)`。最终 `ratio = model_ratio × group_ratio`。计费按请求格式分两条路径：

**① OpenAI / 通用格式**（`relay/compatible_handler.go:336-408`，用 `shopspring/decimal` 精确计算）：

```text
ratio = model_ratio × group_ratio                                    (:276)
base = prompt_tokens
     − cache_tokens        (仅非 Claude 语义时减)
     − cache_create_tokens (仅非 Claude 语义时减)
     − image_tokens
     − audio_tokens        (Gemini 独立音频价时减)

prompt_quota     = base
                 + cache_tokens × cache_ratio
                 + cache_create_tokens × cache_create_ratio
                 + image_tokens × image_ratio
completion_quota = completion_tokens × completion_ratio

quota = (prompt_quota + completion_quota) × ratio                   (:384)
      + gemini_audio_input_quota   (按 1M token 独立价，单独累加)
      + web_search / file_search / image_generation_call 调用计费    (各自独立累加)
```

**② Claude Messages 格式**（`service/quota.go` 的 `PostClaudeConsumeQuota`，275-289 行，区分 5m / 1h 缓存写入）：

```text
quota = prompt_tokens
      + cache_tokens × cache_ratio
      + cache_creation_5m × cache_creation_ratio_5m
      + cache_creation_1h × cache_creation_ratio_1h
      + remaining_creation × cache_creation_ratio   (剩余写入归 5m 基准)
      + completion_tokens × completion_ratio
quota = quota × group_ratio × model_ratio
```

> - OpenAI 路径的缓存写入用**单一** `cache_create_ratio`；只有 Claude 路径区分 5m / 1h。
> - `cache_creation_ratio_1h = cache_creation_ratio × (6/3.75)`（常量 `relay/helper/price.go:17`）。默认 5m 基准 = 1.25 ⇒ 1h ≈ 2.0。
> - 音频 / Realtime 走单独的 `calculateAudioQuota`（`service/quota.go:50-87`）：`text_in + text_out×completion_ratio + audio_in×audio_ratio + audio_out×audio_ratio×audio_completion_ratio`，再 `× model_ratio × group_ratio`。
> - 上游返回的 usage 为 0（如超时）时记 `quota = 0` 并走结算退款。

### 固定价模型（quota_type=1，DALL-E / MJ / Suno 等）

不走 token 倍率，改用 `model_price`（`relay/helper/price.go:96`、`service/quota.go:288`、`relay/compatible_handler.go:390`）：

```text
display_price = model_price × group_ratio
billing_quota = model_price × QuotaPerUnit × group_ratio   （QuotaPerUnit 默认 500000）
```

`quota_type` 由 `model/pricing.go:298-303` 从 `use_price` 派生：模型配了 `model_price` → `quota_type=1`，否则 → `0`（走倍率）。

---

## 计费模型分类

| 计费模型 | quota_type | 字段 | 典型模型 |
|----------|-----------|------|----------|
| 按 token | 0 | `model_ratio` + 各细项 | GPT-4o、Claude、Gemini、DeepSeek 等文本模型 |
| 按次固定价 | 1 | `model_price` | DALL-E、Midjourney、Suno、Replicate |

---

## 三种"做折扣"的玩法（生产场景）

| 业务目标 | 改哪个字段 | 备注 |
|----------|-----------|------|
| **全场统一定价** | 把所有 group 的 `group_ratio` 都设成同一值（如 1.0） | 模型广场全员展示一致 |
| **全场统一下浮 N 折** | 把所有 group 的 `group_ratio` 都 ×N（如 0.8） | 全员一致折扣；促销结束恢复 |
| **VIP 差异化折扣** | 单改某几个 group 的 `group_ratio` | 典型：default=1, vip=0.9, svip=0.8 |
| **B 端 vs C 端交叉定价** | 用 `group_group_ratio` 二维矩阵 | ⚠️ 见坑 2：对未登录访客的展示不生效 |
| **单模型调价** | 改 `model_ratio`（或 `model_price`） | 全员同步，不影响其他模型；但展示有最多 1 分钟缓存延迟 |
| **限时折扣** | 新建折扣 group + 把用户迁过去 | `group_ratio` 改动立即生效 |

---

## 关键易踩坑清单

### 🚨 坑 1：模型广场默认展示"最优分组价"

未登录 / 未筛选分组时（默认 `selectedGroup === 'all'`），前端 `calculateModelPrice`（`web/src/helpers/utils.jsx:625-646`）在**该模型可用分组 ∩ 前端可见的 group_ratio** 中取 `group_ratio` **最小值**作为展示乘数；找不到则回退 1。

- 例：group_ratio = {default: 1, vip: 0.9, svip: 0.8}
- 未登录访问者看到的是 **min × model_ratio = 0.8 × model_ratio**（销售导向）
- 但 default 用户实际扣费是 **1.0 × model_ratio**（按用户真实分组）

➡️ 新用户看到的"价格"不是他注册后会被扣的价格。点击具体分组后会切换为该分组的真实倍率。

### 🚨 坑 2：GroupGroupRatio 对「未登录访客」不生效

`group_group_ratio` 是 `user_group × using_group` 的二维覆盖（`setting/ratio_setting/group_ratio.go`）。

- **后端扣费**：始终生效（`HandleGroupRatio` 命中即覆盖，写入 `log.other.user_group_ratio`）。
- **模型广场展示**：前端不直接读这一层，但**登录用户**的 `/api/pricing`（`controller/pricing.go:24-29`）会把 `GetGroupGroupRatio(user.Group, g)` 合并进返回的 `group_ratio` map，所以**登录用户看到的展示价 = 实际扣费价**。
- 只有**未登录访客**（或跨用户对比时）看到的展示价不包含这层覆盖。

➡️ 生产建议：不用 GroupGroupRatio 的话，保持空配置（默认 `{vip: {edit_this: 0.9}}` 是占位示例，可清空）。

### 🚨 坑 3：没有"全场统一折扣按钮"

newapi 没有"一键全场折扣"开关。要做全场折扣必须**每个 group 都改 group_ratio**。模型越多 + 分组越多，手动工作量越大。

➡️ 建议：在运营 SOP 里固化"全场折扣模板"（如 `default:0.9, vip:0.8, svip:0.7`）。

### 🚨 坑 4：改 model_ratio 不影响历史 log

`log.quota` 是请求完成时的快照值，改 `model_ratio` 不会回溯历史计费。

➡️ 调价前如有争议，先在用户群公告。

### 🚨 坑 5：固定价模型没有 token 倍率

`model_price` × `group_ratio` 是这类模型的全部，不存在 `completion_ratio` 之类的细分。

➡️ 对账时不要按 token × ratio 算，按"次数 × model_price × group_ratio"算。

### 🚨 坑 6：model_ratio 的展示有 1 分钟缓存

`group_ratio` 改动**立即生效**（内存 `RWMap`，`UpdateGroupRatioByJSONString` 直接覆盖）；但 `model_ratio` 改动后，`/api/pricing` 返回的 pricing 数据走 `model.GetPricing()`（`model/pricing.go:63-75`）的 **1 分钟 TTL 缓存**，**最多滞后 1 分钟**才反映到模型广场。

➡️ 客服回答用户"为什么改完价格还没变"时：让用户等 1 分钟后刷新（或硬刷浏览器）。

---

## 关键源码索引

| 关注点 | 文件 |
|--------|------|
| 模型倍率 / 模型价格 / 完成倍率 / 图像音频倍率 | `setting/ratio_setting/model_ratio.go` |
| 缓存命中 / 缓存写入倍率 | `setting/ratio_setting/cache_ratio.go` |
| 分组倍率 / 分组对分组倍率 | `setting/ratio_setting/group_ratio.go` |
| OpenAI 路径扣费公式 | `relay/compatible_handler.go:336-408` |
| Claude 路径扣费公式 | `service/quota.go` `PostClaudeConsumeQuota`（275-289） |
| 音频 / Realtime 扣费 | `service/quota.go` `calculateAudioQuota`（50-87） |
| group_ratio 决定 + GroupGroupRatio 覆盖 + 预扣 | `relay/helper/price.go` `HandleGroupRatio`（20-46）、`ModelPriceHelper`（48-140） |
| 后端定价接口（返回给前端） | `controller/pricing.go:11` `GetPricing` |
| Pricing 数据模型 + 1 分钟缓存 | `model/pricing.go:17-36`、`GetPricing`（63-75） |
| 前端展示价公式 + 取最小分组逻辑 | `web/src/helpers/utils.jsx` `calculateModelPrice`（611-762） |

---

## 给运营/客服的"客户视角"答疑模板

| 客户问 | 答 |
|--------|----|
| 为什么我看到的和别人不一样？ | 因为您所在分组（default / vip / svip）的折扣率不同。注册后即按您所在分组的折扣计算。 |
| 折扣什么时候生效？ | `group_ratio` 改动立即生效（无缓存）；`model_ratio` 改动有**最多 1 分钟**延迟（后端 pricing 缓存）。 |
| 我能否看到全场最优价？ | 可以，未登录或未筛选分组时，模型广场默认展示全场最优价（即所有分组中折扣最低的价格）。 |
| 涨价前已下的订单会被追扣吗？ | 不会，log 表里的是请求发生时的快照 quota。 |
| 为什么 DALL-E 是按次计费而不是按 token？ | 因为 OpenAI 官方按图收费，newapi 用 `model_price`（固定价）字段承载，扣费 = `model_price × group_ratio`。 |

---

## 速记口诀

> **模型定价 = 一致性基础价**
> **分组定价 = 差异化乘数**
> **显示 ≈ 扣费 = 模型 × 分组**
> **做全场 = 改全部分组**
> **做差异 = 改单个分组**

---

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-07-25 | 初版，与 `PRODUCT_CAPABILITIES.md` 配套 |
| 2026-07-27 | 按真实源码校正：前端公式定位到 `web/src/helpers/utils.jsx`；后端公式改为 OpenAI（`relay/compatible_handler.go`）/ Claude（`service/quota.go`）双路径；修正 `×2` 硬编码说明、GroupGroupRatio 对登录用户生效、model_ratio 1 分钟缓存等错误 |

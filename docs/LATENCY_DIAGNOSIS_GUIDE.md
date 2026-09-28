# newapi 模型响应慢诊断与加速手册（耗时排障 Runbook）

> 团队运维 / 客服 排障手册：用户反馈"响应慢"时，按本手册快速定位故障段。
> 核心问题只有一个：**慢在接入层（CDN/WAF/网络）？中转站？还是后端渠道（上游）？**
> 配套阅读：`docs/CHANNEL_AFFINITY_GUIDE.md`（渠道亲和加速）、`docs/BILLING_TROUBLESHOOTING.md`
> 适用版本：newapi 主干

---

## 目录

1. [链路模型与耗时构成](#1-链路模型与耗时构成)
2. [5 分钟快速判定](#2-5-分钟快速判定)
3. [第一步：分段计时复现请求](#3-第一步分段计时复现请求)
4. [第二步：排除接入层（CDN/网络）](#4-第二步排除接入层cdn网络)
5. [第三步：中转站自查（日志三件套）](#5-第三步中转站自查日志三件套)
6. [第四步：上游渠道排查](#6-第四步上游渠道排查)
7. [故障模式速查表](#7-故障模式速查表)
8. [优化建议与加速方案](#8-优化建议与加速方案)
9. [实战案例](#9-实战案例)
10. [附录：现成脚本](#10-附录现成脚本)

---

## 1. 链路模型与耗时构成

一次 chat 请求的完整链路：

```
客户端 ──①──> [CDN / WAF / 负载均衡] ──②──> newapi 中转站 ──③──> 上游渠道（供应商）
```

总耗时 ≈ ① 接入网络 + ② 中转站处理 + ③ 上游等待与传输

**关键认知（先记住，后面全靠它）：**

| 事实 | 依据 |
|------|------|
| 中转站自身处理极快（轻量接口 ~40ms 级） | Go + 内存缓存路由，无重逻辑 |
| 大部分"慢"来自 ③：上游首 token（排队/推理/链路） | 模型生成本身需要时间 |
| 接入层 ① 可能引入成倍延迟，且最容易被忽视 | CDN 对流式 API 常见回源绕路、缓冲 |
| newapi 日志的 `use_time` / `frt` **不含** ① 段 | 日志从中转站视角记录 |

因此判定的核心手法是**对照实验**：同一请求，改一个变量（绕过 CDN / 换轻量接口 / 查日志），看哪一段的数字对不上。

---

## 2. 5 分钟快速判定

用户反馈慢时，先做两件事再深入：

1. **拿到要素**：用户用的模型、流式还是非流式、哪个接入域名、大致时间点。
2. **跑下面的决策表**：

| 现象 | 最可能的故障段 | 下一步 |
|------|----------------|--------|
| 轻量接口（`/api/status`、`/v1/models`）也慢（>1s） | **接入层**（CDN/网络/DNS） | §4 直连源站对照 |
| 轻量接口快，chat 慢，且日志 `frt` 高 | **上游渠道慢** | §6 渠道测速对比 |
| 轻量接口快，chat 慢，但日志 `frt`/`use_time` 低 | **接入层或客户端侧**（中转+上游都快，慢在路上） | §4，让用户侧抓分段计时 |
| 日志出现"重试：渠道A->渠道B" | **渠道故障 + 重试叠加**（偶发超慢的常见原因） | §5.3 查渠道错误 |
| 流式请求"憋很久一次性吐完" | **CDN 缓冲了 SSE** | §4.2 节奏分析 |
| 只有某些用户慢、其他用户正常 | 用户侧网络 / 接入线路地域差异 | 用户侧分段计时 |

决策表命中不了再走完整四步：§3 分段计时 → §4 排除接入层 → §5 中转站日志 → §6 上游。

---

## 3. 第一步：分段计时复现请求

用 `curl -w` 拆解各阶段耗时。**必须复现用户参数**：同模型、同流式/非流式、同接入域名。

```bash
KEY="sk-xxxx"   # 测试用令牌（诊断后删除）
BODY='{"model":"<用户反馈的模型>","messages":[{"role":"user","content":"hi"}],"max_tokens":16}'

# 非流式
curl -sS -o /dev/null -w 'dns=%{time_namelookup}s tcp=%{time_connect}s tls=%{time_appconnect}s ttfb=%{time_starttransfer}s total=%{time_total}s http=%{http_code}\n' \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "$BODY" https://<接入域名>/v1/chat/completions

# 流式（加 -N 禁缓冲，另加 stream 字段）
```

**指标解读：**

| 指标 | 计算 | 含义 |
|------|------|------|
| TCP 建连 | `time_connect` | ≈ 客户端到接入点的 RTT |
| TLS 握手 | `time_appconnect - time_connect` | 接入点握手成本 |
| 首字节 TTFB | `time_starttransfer` | ①+②+③ 的首字节总账 |
| 应用等待 | `ttfb - time_appconnect` | 中转站 + 上游的等待 |
| 总耗时 | `time_total` | 完整收完响应 |

**采样规范：每个实验跑 3~5 次取中位数。** 单次结果会受偶发抖动误导；如果两次采样差接近 1s，本身就说明该层波动大（这本身就是证据，见 §9 案例）。

---

## 4. 第二步：排除接入层（CDN/网络）

### 4.1 直连源站对照（判定接入层贡献）

如果源站在自管（未走代理），用 `--resolve` 把域名强行指到源站 IP，其余完全不变：

```bash
# 经 CDN（正常解析）
curl -sS -o /dev/null -w 'A: ttfb=%{time_starttransfer}s total=%{time_total}s\n' ... https://<域名>/api/status

# 直连源站（SNI 仍是原域名，仅改路由）
curl -sS -o /dev/null --resolve <域名>:443:<源站IP> -w 'B: ttfb=%{time_starttransfer}s total=%{time_total}s\n' ... https://<域名>/api/status
```

**判读：**

- **B 明显快于 A**（如 A≈1.2s、B≈0.13s）→ 接入层引入了延迟，慢点在 CDN/WAF/回源链路
- **A ≈ B** → 接入层没问题，慢在中转之后的段，转 §5

对照时优先用轻量接口（`/api/status`、`/v1/models`）：它们由中转站直接应答，不涉及上游，最能干净地暴露接入层成本。

### 4.2 识别 CDN 缓冲 SSE（流式场景专属坑）

部分 CDN/全站加速会缓冲响应体。流式请求下有一个强特征：

- **正常透传**：TTFB（首字节）≪ total，chunk 到达均匀
- **被缓冲**：TTFB ≈ total，数据憋到最后一次性吐出

用附录脚本 A 记录每个 SSE chunk 的到达时间：gap 均匀（~0.1s 级）为正常；出现秒级大 gap 或末尾集中到达即缓冲/卡顿。

---

## 5. 第三步：中转站自查（日志三件套）

中转站是不是慢，看日志，不看感觉。日志表（`logs`）与请求级字段：

| 字段 | 含义 | 排查用法 |
|------|------|----------|
| `use_time` | 请求总耗时（秒，中转站视角） | 找慢请求 |
| `other.frt` | **首响应毫秒数**（收到上游首字节 - 请求开始） | 区分"慢在上游首 token"还是"慢在生成传输" |
| 重试日志 | 文本含 `重试：渠道A->渠道B` | 偶发超慢的放大器 |

### 5.1 frt 是"上游慢"的权威指标

`frt = FirstResponseTime - StartTime`（`service/log_info_generate.go`），覆盖了中转站选路 + 上游排队 + 上游首 token。

- `frt` 高（如 flash 级模型 >2s）→ 慢在上游（或选到了差渠道）→ §6
- `frt` 低但 `use_time` 高 → 上游首字节快，慢在生成传输（长输出、上游吞吐低、或接入层传输慢）
- `frt`、`use_time` 都低，但用户仍喊慢 → 慢在 ① 段（用户到中转站的网络），让用户侧抓 §3 分段计时

### 5.2 找慢请求

```sql
-- 最近 24h 最慢的 20 条（跨 SQLite/MySQL/PostgreSQL 通用）
SELECT created_at, model_name, use_time, other
FROM logs WHERE type = 2
  AND created_at > <unix_now - 86400>
ORDER BY use_time DESC LIMIT 20;
```

`other` 字段 JSON 里看 `frt`、`admin_info`（含渠道饱和审计）、重试信息。后台"日志"页可直接看详情。

### 5.3 重试叠加：偶发超慢的头号嫌疑

失败请求会切换渠道重试（`controller/relay.go`），每次重试 = 一次完整失败等待的叠加。`RETRY_TIMES` 默认 0，生产常配 3：如果第一个渠道挂着但要等满超时才报错，用户一次请求可能承受 3~4 倍超时。

- 日志里高频出现 `重试：` → 先修/禁用问题渠道，而不是调大重试
- 重试日志中的渠道名就是病灶

### 5.4 中转站自身基线

`/api/status` 应用处理应在 **~100ms 级以内**（不含网络 RTT）。若直连源站测得该接口应用等待仍高，才考虑中转站本身问题（DB 慢查询、Redis 抖动、节点负载），用 `top`/DB 慢查询日志进一步定位——这种情况在多节点 + 外置 DB 架构下很少见。

---

## 6. 第四步：上游渠道排查

日志确认 `frt` 高后，定位到具体渠道：

1. **后台渠道测试**："渠道"页对同模型的多个渠道逐一"测试"，横向对比响应时间；异常渠道会报错或明显慢
2. **复核上游首 token**：用同一测试 prompt 直连各渠道的上游地址 + 渠道密钥，绕过中转站测 `ttfb`——直连上游也慢，就是供应商的问题（排队/链路），找供应商或换渠道
3. **生成速率**：`use_time - frt ≈ 生成传输时间`。首字节快、整句慢 → 上游吞吐低或输出过长
4. **渠道权重**：同模型多渠道时，按实测速度调权重，慢渠道降权（配置见 `docs/CHANNEL_AFFINITY_GUIDE.md`）

视频生成类（seedance 等）走异步任务模式，不在本手册"响应慢"范畴；其慢体现在任务轮询完成时长，按平台任务维度排查。

---

## 7. 故障模式速查表

| # | 模式 | 强特征 | 根因 | 处理 |
|---|------|--------|------|------|
| 1 | CDN 引入延迟 | 轻量接口经域名慢、直连源站快 9 倍+；run 间波动大 | 回源链路绕路、边缘节点质量差 | API 域名绕过 CDN（§8.1） |
| 2 | CDN 缓冲 SSE | 流式 TTFB ≈ total，chunk 末尾集中到达 | CDN 不透传流式 | 关缓冲/换透传线路/绕过 CDN |
| 3 | 上游首 token 慢 | `frt` 持续高，直连上游同样慢 | 供应商排队、链路绕路 | 多渠道冗余、降权慢渠道、找供应商 |
| 4 | 渠道故障重试叠加 | 日志 `重试：A->B` 高频，偶发数倍超慢 | 死渠道拖满超时才切换 | 修/禁病灶渠道，配渠道超时 |
| 5 | 生成吞吐低 | `frt` 低、`use_time - frt` 高 | 上游模型吞吐低 | 换渠道/供应商 |
| 6 | 用户侧网络慢 | 日志 frt/use_time 都正常，仅部分用户慢 | 用户到接入点线路差 | 用户侧抓分段计时确认 |
| 7 | 中转站自身慢 | 直连源站测 `/api/status` 应用等待也 >100ms | DB/Redis/负载 | 查慢查询与节点负载 |

---

## 8. 优化建议与加速方案

按投入产出比排序，分三层实施。

### 8.1 接入层（收益最大，往往零成本）

1. **API 域名与控制台域名分离；API 调用不走 CDN。** LLM API 是程序化、流式长连接场景，CDN 只增加延迟（实测可 +0.6~1.8s/请求，见 §9）没有收益：控制台网页继续走 CDN 加速静态资源，API 域名 DNS 直接 A 记录到源站
2. **必须保留 CDN/WAF 时**（防 DDoS、隐藏源站）：确认支持 SSE/WebSocket 透传、回源读超时 ≥600s、动态请求禁缓存；用 §4.1 的对照实验定期验收边缘节点质量
3. **客户端连接复用**：SDK 默认开启 keep-alive 时 TLS 握手只付一次；高频短请求场景收益明显
4. **跨境线路**：大陆用户访问香港/海外节点，优先 CN2/IEPL 优化线路或就近部署节点；纯海外用户直连通常已最优

### 8.2 中转站层

1. **渠道超时 + 合理 RETRY_TIMES**：重试保成功率但叠加尾延迟，治本靠"快速失败 + 病灶渠道禁用"，不要靠堆重试次数
2. **渠道亲和**（`docs/CHANNEL_AFFINITY_GUIDE.md`）：同一会话粘住同一渠道，命中上游 prompt cache——首 token 延迟与费用双降，对长上下文场景收益极大
3. **定时渠道测试 + 自动禁用**：后台配置定时测试，慢/挂渠道自动下线，流量自动切到健康渠道
4. **按实测速度调渠道权重**：同模型多渠道不等于高可用，权重不当时流量仍会打到慢渠道

### 8.3 上游/业务层

1. **同模型多供应商冗余**：任一供应商排队/抖动时流量自然分流
2. **引导客户端用流式**：流式首 token 到达即可渲染，体感延迟远低于非流式等全量
3. **模型分层路由**：轻任务（分类、摘要、闲聊）路由到 flash/mini 级模型，首 token 快且成本低
4. **长上下文命中缓存**：稳定 system prompt + 渠道亲和，让上游 prompt cache 生效

---

## 9. 实战案例

**背景**：某部署在香港的节点，API 域名配置了全站 CDN（境外加速），用户反馈响应慢。

**实验 1：轻量接口 `/api/status`，经 CDN vs 直连源站，各 3 次：**

| 路径 | TLS 完成 | 首字节 TTFB |
|------|----------|-------------|
| 经 CDN | ~0.66s | 1.15s / 1.93s / 1.17s |
| 直连源站 | ~0.09s | 0.125~0.134s |

→ 中转站应用处理仅 ~40ms；CDN 路径 TLS 多花 ~0.57s，首字节慢 **9~14 倍**且波动大。

**实验 2：16-token 非流式 chat（同一 flash 模型）：**

| 路径 | 首字节 TTFB |
|------|-------------|
| 经 CDN | 3.1~4.1s |
| 直连源站 | 2.4~2.5s |

**实验 3：流式 chunk 节奏（附录脚本 A）：** 两条路径均透传正常（无缓冲），CDN 路径偶发 0.38~0.42s 卡顿，直连均匀。

**结论分解**：中转站 ~40ms（无问题）｜CDN 每请求 +0.6~1.8s（主犯之一）｜上游首 token ~2.3s（16-token 小请求直连也这么慢，上游偏慢）。

**处理**：API 子域名绕过 CDN（用户侧立即提速 ~1s）；对 flash 模型渠道做测速与降权，治理上游首 token。

---

## 10. 附录：现成脚本

### 0. 一键全流程：`docs/scripts/latency_doctor.py`

自动执行本手册 §3~§7 全部实验（分段计时 → 直连源站对照 → SSE 节奏 → 分段判定）并输出结论，退出码非 0 表示发现慢段：

```bash
python3 docs/scripts/latency_doctor.py \
  --base-url https://<接入域名> --key sk-xxx --model <用户反馈的模型> \
  --origin-ip <源站IP>        # 可选；提供后 chat/上游实验走直连源站（路径B），并输出 CDN 对照差值
```

脚本自动还原 DNS/CNAME 链并判定链路形态（是否经过 CDN/WAF 中间层），输出端到端总耗时（用户视角）与分段账本。路径A = 经接入链路（用户真实路径）；路径B = 直连源站（剥离接入层，需 `--origin-ip`）。未提供 `--origin-ip` 时全部实验走路径A，接入层与中转站无法拆分，账本与结论会相应标注；流式实验固定走路径A（CDN 缓冲只可能发生在接入链路上）。`--list-models` 仅列出中转站可用模型后退出。

依赖 python3 与 curl；阈值可在脚本头部调整。以下 A/B 为手工拆解场景时使用。

### A. SSE chunk 到达节奏分析（识别缓冲/卡顿）

```bash
KEY="sk-xxxx"; URL="https://<接入域名>/v1/chat/completions"
BODY='{"model":"<模型>","messages":[{"role":"user","content":"count 1 to 30"}],"max_tokens":80,"stream":true}'

curl -sS -N -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d "$BODY" "$URL" | python3 -c '
import sys, time
start = None; chunks = []
for line in sys.stdin:
    line = line.strip()
    if line.startswith("data:") and "[DONE]" not in line:
        now = time.time()
        if start is None: start = now
        chunks.append(now - start)
if chunks:
    gaps = [round(b - a, 2) for a, b in zip(chunks, chunks[1:])]
    print(f"chunks={len(chunks)} 首chunk={chunks[0]:.2f}s 末chunk={chunks[-1]:.2f}s")
    print(f"gap分布={gaps[:40]}")
'
```

判读：gap 均匀（0.05~0.2s）= 正常透传；秒级大 gap 或末尾集中 = 缓冲/卡顿。

### B. 快速对照函数（放到 shell 配置里随取随用）

```bash
api_timing() {  # api_timing <域名> <模型> [源站IP]   依赖环境变量 API_KEY
  local host="$1" model="$2" body extra=""
  body='{"model":"'"$model"'","messages":[{"role":"user","content":"hi"}],"max_tokens":16}'
  [ -n "$3" ] && extra="--resolve $host:443:$3"
  for i in 1 2 3; do
    curl -sS -o /dev/null $extra -w "run$i: tls=%{time_appconnect}s ttfb=%{time_starttransfer}s total=%{time_total}s http=%{http_code}\n" \
      -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "$body" "https://$host/v1/chat/completions"
  done
}
# 用法：API_KEY=sk-xxx; api_timing api.example.com gpt-4o-mini            # 经接入链路
#       API_KEY=sk-xxx; api_timing api.example.com gpt-4o-mini 1.2.3.4   # 直连源站对照
```

### C. 排障检查单（打印版）

```
□ 1. 记录要素：模型 / 流式? / 接入域名 / 时间点
□ 2. curl -w 分段计时 ×3，记录 ttfb / total
□ 3. /api/status 同法 ×3 → 慢?  → 接入层，做直连源站对照
□ 4. 直连源站对照：差值 = 接入层贡献
□ 5. 查日志：use_time / frt / 是否有"重试："
□ 6. frt 高 → 渠道测试对比 → 直连上游复核 → 定位供应商
□ 7. 流式异常 → 附录 A 节奏分析
□ 8. 出结论：接入层 / 中转站 / 上游，三方数据写进工单
```

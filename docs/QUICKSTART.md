# New API 快速部署与功能速览

> 本文档是本仓库自建中文文档的**入口**：3 分钟把服务跑起来 → 生产环境上线 → 知道系统能干什么、深入文档在哪。
>
> 部署遇到问题先看本文「常见问题」；计费扣费问题看 [BILLING_TROUBLESHOOTING.md](BILLING_TROUBLESHOOTING.md)。

## 📚 本仓库文档地图

| 文档 | 什么时候看 |
|------|-----------|
| **本文** — 快速部署与功能速览 | 部署、配置、找功能入口 |
| [PRODUCT_CAPABILITIES.md](PRODUCT_CAPABILITIES.md) — 产品能力全景 | 想全面了解系统 15 个能力域（架构/渠道/计费/权限/运维…） |
| [BILLING_MODEL.md](BILLING_MODEL.md) — 计费与定价模型速查 | 搞懂价格链、倍率公式、三种折扣玩法、易踩坑清单 |
| [BILLING_TROUBLESHOOTING.md](BILLING_TROUBLESHOOTING.md) — 计费异常排查 Runbook | 扣费比预期多/少、展示价与扣费不一致等场景 |
| [../newapi_llm_deployment_plan.md](../newapi_llm_deployment_plan.md) — 完整部署方案 | 需要整体部署架构与规划细节（含多节点架构章节） |

---

## 第一段：3 分钟试用（单机 Docker Compose）

适用：本地体验、功能验证。自带 PostgreSQL + Redis，一条命令全起。

**前置**：已安装 Docker（含 compose 插件）。

```bash
# 克隆仓库
git clone https://github.com/Feng-jia-hqx/self-newapi.git
cd self-newapi

# 直接启动（new-api + postgres + redis）
docker compose up -d

# 确认三个容器都健康
docker compose ps
```

启动后：

- 访问 `http://localhost:3000`
- 默认管理员账号：`root` / `123456`（**首次登录后立即修改密码**，路径：个人设置）
- 健康检查接口：`http://localhost:3000/api/status`

最简方式（不用 compose，SQLite 单容器）：

```bash
docker run --name new-api -d --restart always \
  -p 3000:3000 \
  -e TZ=Asia/Shanghai \
  -v ./data:/data \
  calciumion/new-api:latest
```

常用运维命令：

```bash
docker compose logs -f new-api   # 看日志
docker compose down              # 停止（数据保留在 ./data 与 pg_data 卷）
docker compose pull && docker compose up -d   # 升级到最新镜像
```

> ⚠️ `docker-compose.yml` 里 PostgreSQL/Redis 密码是默认值（`123456`），仅限试用。生产环境见下一段。

---

## 第二段：生产部署（外置 MySQL + Redis 多节点）

适用：正式上线、横向扩展。使用 [../docker-compose-mysql.yml](../docker-compose-mysql.yml)，数据库与缓存由外部实例提供，compose 只管 new-api 节点本身。

**前置**：

- 已有外部 MySQL（≥ 5.7.8）和 Redis 实例，网络可达
- MySQL 中预先创建好空数据库（建议 `utf8mb4` 字符集）
- 每台节点服务器都已安装 Docker

**步骤**：

1. **准备密钥**（所有节点必须使用相同的值）：

   ```bash
   openssl rand -hex 32   # 生成 SESSION_SECRET
   openssl rand -hex 32   # 再生成一个 CRYPTO_SECRET
   ```

2. **修改 compose 配置**，将 `docker-compose-mysql.yml` 中的以下值替换为真实值：

   | 变量 | 说明 |
   |------|------|
   | `SQL_DSN` | 外部 MySQL 地址，格式 `user:password@tcp(host:3306)/new-api` |
   | `REDIS_CONN_STRING` | 外部 Redis 地址，格式 `redis://:password@host:6379` |
   | `SESSION_SECRET` | 上一步生成，**所有节点一致** |
   | `CRYPTO_SECRET` | 上一步生成，**所有节点一致** |

3. **指定节点角色**：

   - **Master 节点**：保持 `NODE_TYPE` 注释状态（默认 master），负责数据库迁移、后台任务
   - **Slave 节点**：取消注释 `- NODE_TYPE=slave`，纯转发节点
   - 可选：`FRONTEND_BASE_URL=http://master-ip:3000`（slave 前端页面重定向到 master，API 请求不受影响）、`NODE_NAME`（运维标识）

4. **逐节点启动**：

   ```bash
   docker compose -f docker-compose-mysql.yml up -d
   ```

   首个启动的 master 节点会自动完成建表迁移。

5. **前置负载均衡**：Nginx / HAProxy 将流量分发到各节点 3000 端口（节点本身无状态，状态都在 MySQL/Redis）。

**验证**：

```bash
curl -s http://<节点IP>:3000/api/status | grep success
# 每个节点都应返回 "success": true
```

**生产 checklist**：

- [ ] 已修改 root 默认密码
- [ ] `GIN_MODE=release`（compose 中已配置）
- [ ] MySQL/Redis 密码为强密码，且不在公网裸奔
- [ ] 日志轮转已生效（compose 已配置 10MB × 3 份）
- [ ] 升级流程演练过：`docker compose -f docker-compose-mysql.yml pull && docker compose -f docker-compose-mysql.yml up -d`

---

## 上线后首次配置（5 步走）

1. **添加渠道**：控制台 → 渠道 → 添加，填入上游提供商的 API Key（支持 50+ 提供商，见 [能力文档 §6](PRODUCT_CAPABILITIES.md#6-渠道与路由分发)）
2. **确认模型倍率**：控制台 → 设置 → 运营设置，检查模型倍率 / 分组倍率 / 补全倍率（原理见 [BILLING_MODEL.md](BILLING_MODEL.md)）
3. **创建用户与分组**：按需创建分组并设置分组倍率（做差异化定价）
4. **发放令牌**：用户在个人中心创建 API 令牌（可设额度、过期时间、模型限制）
5. **客户端接入**：Base URL 填 `http(s)://你的域名`，与 OpenAI API 兼容：

   ```bash
   curl http://localhost:3000/v1/chat/completions \
     -H "Authorization: Bearer sk-你的令牌" \
     -H "Content-Type: application/json" \
     -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "hello"}]}'
   ```

---

## 功能速览（一表索引）

详细内容见 [PRODUCT_CAPABILITIES.md](PRODUCT_CAPABILITIES.md)，共 15 章：

| 能力域 | 一句话说明 | 详情 |
|--------|-----------|------|
| 🎯 产品定位 | 统一 AI 网关 + 多租户计费运营平台 | [§1](PRODUCT_CAPABILITIES.md#1-产品定位与核心价值) |
| 🏗 整体架构 | 分层架构与目录导览 | [§2](PRODUCT_CAPABILITIES.md#2-整体架构与目录) |
| 🤖 上游适配 | 50+ 提供商、跨协议转换（OpenAI/Claude/Gemini 互转） | [§3](PRODUCT_CAPABILITIES.md#3-ai-上游适配能力) |
| 👤 用户权限 | 三层账户模型、分组、令牌 | [§4](PRODUCT_CAPABILITIES.md#4-用户与权限体系) |
| 🔐 认证登录 | 密码 / 2FA / Passkey / OAuth 登录矩阵 | [§5](PRODUCT_CAPABILITIES.md#5-认证与登录方式) |
| 🔀 渠道路由 | 渠道抽象、权重与重试、模型重定向 | [§6](PRODUCT_CAPABILITIES.md#6-渠道与路由分发) |
| 💰 计费配额 | 倍率与表达式计费、预扣与结算 | [§7](PRODUCT_CAPABILITIES.md#7-计费表达式与配额系统)（速查：[BILLING_MODEL.md](BILLING_MODEL.md)） |
| 💳 充值支付 | 充值、支付与订阅管理 | [§8](PRODUCT_CAPABILITIES.md#8-充值与支付订阅) |
| 🛠 后台运营 | 控制台管理与运营能力 | [§9](PRODUCT_CAPABILITIES.md#9-后台管理与运营) |
| 📈 可观测 | 日志、审计、用量排行 | [§10](PRODUCT_CAPABILITIES.md#10-可观测日志与审计) |
| 🛡 安全限流 | 速率限制与安全机制 | [§11](PRODUCT_CAPABILITIES.md#11-安全与速率限制) |
| 🖥 前端能力 | 控制台 UI 与模型广场 | [§12](PRODUCT_CAPABILITIES.md#12-前端能力) |
| 🔧 辅助能力 | OAuth / 邮件 / 文件缓存等 | [§13](PRODUCT_CAPABILITIES.md#13-辅助能力oauth--邮件--passkey--文件--缓存) |
| 🚢 运维部署 | 部署形态与运维要点 | [§14](PRODUCT_CAPABILITIES.md#14-运维与部署) |
| 📡 API 概览 | 全部管理/用户/中转接口清单 | [§15](PRODUCT_CAPABILITIES.md#15-api-接口概览) |

---

## 常用环境变量速查

完整列表见 [官方环境变量文档](https://docs.newapi.pro/en/docs/installation/config-maintenance/environment-variables)，以下为最常用的：

| 变量 | 默认 | 说明 |
|------|------|------|
| `SQL_DSN` | SQLite | 数据库连接串（PG: `postgresql://…`，MySQL: `user:pass@tcp(host)/db`） |
| `REDIS_CONN_STRING` | 无 | Redis 连接串，配置后启用缓存与多节点共享状态 |
| `SESSION_SECRET` | 随机 | 登录会话加密密钥，**多节点必须一致** |
| `CRYPTO_SECRET` | 无 | 敏感数据加密密钥，**多节点必须一致** |
| `NODE_TYPE` | master | `slave` 时该节点不做迁移与后台任务 |
| `GIN_MODE` | debug | 生产设 `release` |
| `STREAMING_TIMEOUT` | 300 | 流式响应无输出超时（秒），空补全时可调大 |
| `SYNC_FREQUENCY` | 60 | 缓存从数据库同步的间隔（秒） |
| `TZ` | UTC | 时区，建议 `Asia/Shanghai` |

---

## 常见问题快速索引

| 症状 | 去哪看 |
|------|--------|
| 扣费比预期多/少 | [BILLING_TROUBLESHOOTING.md](BILLING_TROUBLESHOOTING.md) 场景 1 / 2 |
| 模型广场展示价 ≠ 实际扣费 | [BILLING_TROUBLESHOOTING.md](BILLING_TROUBLESHOOTING.md) 场景 3 |
| 想给某些用户/分组打折 | [BILLING_MODEL.md](BILLING_MODEL.md) 「三种做折扣的玩法」 |
| 流式响应中断 / 空补全 | 调大 `STREAMING_TIMEOUT`（默认 300 秒） |
| 多节点登录态丢失 | 检查各节点 `SESSION_SECRET` 是否一致 |
| 容器反复重启 | `docker logs new-api` 看启动报错，多为 `SQL_DSN` / `REDIS_CONN_STRING` 连不通 |

# OpenClaw web_search 接入（SearXNG 自托管）

> 本目录记录如何在家庭内网用 **SearXNG** 为 **OpenClaw** 提供 `web_search` 能力，
> 包括部署、接入、以及排查过程中踩过的所有坑。
>
> 适用环境：OpenClaw 2026.9.x（Docker）+ SearXNG 2026.9.x（Docker），Ubuntu 内网主机。

---

## 一、为什么用 SearXNG

OpenClaw 内置的 web-search provider 分两类：

| 类型 | provider | 说明 |
|------|----------|------|
| 付费 key | tavily / brave / serper / exa / firecrawl / kimi 等 | 需要 API key |
| 免 key / 自托管 | **duckduckgo**（requiresCredential=false） | 内网可达性常不佳 |
| 免 key / 自托管 | **searxng** | 自托管，`SEARXNG_BASE_URL`，推荐 |

在家庭内网（容器网络、curl_cffi 客户端）环境下，直接访问境外引擎往往超时/被验证码拦截，
因此**推荐自托管 SearXNG + 国内可直连的引擎（360search / quark）**。

---

## 二、部署 SearXNG（Docker + Redis）

### 2.1 目录结构

```
/home/docker/searxng/
├── docker-compose.yml
└── settings.yml
```

镜像在境外直连不通时，用镜像加速拉取后打回标准 tag：

```bash
docker pull docker.m.daocloud.io/searxng/searxng:latest
docker tag docker.m.daocloud.io/searxng/searxng:latest searxng/searxng:latest
```

### 2.2 docker-compose.yml

见同目录 [`docker-compose.yml`](./docker-compose.yml)。
端口映射 `8088 -> 8080`，内置 redis 做结果缓存。

### 2.3 settings.yml（关键！）

见同目录 [`settings.yml`](./settings.yml)。

**核心要点：**
1. `use_default_settings.engines.keep_only: [quark, 360search, wikipedia]` —— 只保留这三个引擎文件；
2. **`360search` / `quark` 在 SearXNG 上游默认配置中本就是 `disabled: true`**，
   `keep_only` 只是「保留下 / 剔除其余的」，**并不会启用被禁用的引擎**；
3. 必须再在顶层 `engines:` 块为每个要用的引擎显式写 `disabled: false`，默认聚合才会真正调用它们。

启动：
```bash
cd /home/docker/searxng
docker compose up -d
# 验证
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8088/   # 200
```

### 2.4 引擎可用性实测（本机结论）

| 引擎 | 状态 | 说明 |
|------|------|------|
| **360search** | ✅ 稳定 | 中文结果主力 |
| **quark** | ⚠️ 基本可用 | 请求过快偶发「意外崩溃」（阿里 X5SEC 验证码） |
| wikipedia | ✅ | 提供 infobox |
| google / baidu | ❌ | 触发验证码 suspended |
| duckduckgo / brave | ❌ | curl_cffi 请求超时 |
| bing | ❌ | 对中国版页面静默返回 0 条 |
| sogou | ❌ | 解析异常 |

---

## 三、接入 OpenClaw

在 OpenClaw 容器 `openclaw-gateway` 内执行：

```bash
# 1. 安装官方 SearXNG 插件（自动 enabled 并加入 allow）
node dist/index.js plugins install clawhub:@openclaw/searxng-plugin

# 2. 配置 SearXNG 地址（免重启生效）
node dist/index.js config set \
  plugins.entries.searxng.config.webSearch.baseUrl \
  '"http://192.168.254.83:8088/"'

# 3. THE KEY：启用 web_search 工具并指定默认 provider（否则 chat 提示 no provider）
node dist/index.js config set tools.web.search.enabled  true
node dist/index.js config set tools.web.search.provider searxng

# 4. 重载插件
node dist/index.js plugins reload searxng

# 5. 命令行实测
node dist/index.js infer web search \
  --provider searxng --query '北京今天天气' --limit 5 --json
```

### 3.1 结构关系（务必分清三层）

| 层级 | 配置 | 作用 |
|------|------|------|
| **工具级** | `tools.web.search.enabled` / `.provider` / `.maxResults` ... | 决定 chat/web 是否启用 web_search 以及**选哪个 provider** |
| **插件级** | `plugins.entries.searxng.config.webSearch.baseUrl` / `.categories` / `.language` | 只描述 SearXNG 实例参数，**不决定选择** |
| **provider** | `infer web providers` | 展示 available/configured/selected |

> 易踩坑：只配插件 `baseUrl`、只 `plugins install` 并不会让 chat 里的 web_search 可用，
> 必须设置 `tools.web.search.{enabled,provider}` 才会把 searxng 选为默认
> （`infer web providers` 中 searxng 会从 `selected=false` 变为 `selected=true`）。

---

## 四、排查经验汇总（血泪坑）

### 坑 1：默认聚合搜索返回 0 条，但显式 `&engines=` 正常
- 现象：URL 带 `engines=quark` 或 `engines=360search` 有结果，不带则 0 条。
- 根因：**`engines=` 会绕过 disabled 禁用标记**，而默认聚合严格执行 disabled。
- 解法：确认目标引擎在顶层 `engines:` 里 `disabled: false`。
- 验证手段（容器内，用 venv python 读真实合并结果）：
  ```bash
  docker exec -e PYTHONPATH=/usr/local/searxng -w /usr/local/searxng searxng \
    /usr/local/searxng/.venv/bin/python -c \
    "import yaml;d=yaml.safe_load(open('/etc/searxng/settings.yml'));print(d['engines'])"
  ```
  > 注意 SearXNG 的 `searx.settings` 是 **dict** 不是对象；正确解释器在 `/usr/local/searxng/.venv/bin/python`（容器内 `/usr/sbin/python3` 缺第三方依赖）。

### 坑 2：容器重启后结果仍为空 → 清 Redis
- `docker restart` 不会清 `/tmp` 下的 SQLite 结果缓存或 Redis。
- 结果异常时清缓存：
  ```bash
  docker exec searxng-redis redis-cli FLUSHALL
  ```

### 坑 3：`duckduckgo_lite` 注册失败
- 引擎名含下划线 `_`，SearXNG 拒绝注册（`Engine name contains underscore`）。不要写进 engines。

### 坑 4：OpenClaw 容器内 CLI 连不上网关（端口推导错误）
- 现象：`devices list` / `health` 报 `ECONNREFUSED ws://127.0.0.1:10084`。
- 根因：容器 env `OPENCLAW_GATEWAY_PORT=10084`，但容器内实际监听 **18789**
  （`10084` 是宿主 docker-proxy 的映射端口）。
- 解法：显式指定 `--url ws://127.0.0.1:18789 --password <pwd>`，别依赖自动推导。

### 坑 5：浏览器访问 Control UI 提示「需在 Gateway 主机批准一次」
- 现象：`[ws] code=1008 reason=pairing required: device is not approved yet`。
- 关键：`gateway.controlUi.dangerouslyDisableDeviceAuth: true` **不会**跳过 WebSocket 设备配对。
- 解法：在容器内批准该浏览器设备（设备会变持久 Paired，之后不再提示）：
  ```bash
  node dist/index.js devices approve --url ws://127.0.0.1:18789 --password <pwd> <requestId>
  node dist/index.js devices list   --url ws://127.0.0.1:18789 --password <pwd>
  ```

### 坑 6：登录方式从 Gateway Token 改为密码
```bash
node dist/index.js config set gateway.auth.mode     password
node dist/index.js config set gateway.auth.password <新密码>
node dist/index.js config set gateway.controlUi.dangerouslyDisableDeviceAuth true  # 内网免设备认证
# 重启生效
docker restart openclaw-gateway
```

---

## 五、验证端到端

```bash
# 1. SearXNG 首页
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.254.83:8088/

# 2. SearXNG JSON 搜索（默认聚合）
curl -s 'http://192.168.254.83:8088/search?q=%E5%8C%97%E4%BA%AC%E5%A4%A9%E6%B0%94&format=json' \
  -H 'Accept: application/json' | python3 -m json.tool | head

# 3. OpenClaw provider 状态（searxng 应为 selected=true）
docker exec openclaw-gateway node dist/index.js infer web providers

# 4. OpenClaw 真实搜索
docker exec openclaw-gateway node dist/index.js infer web search \
  --provider searxng --query '北京今天天气' --limit 5 --json
```

预期返回：`ok=true`、`count>=1`、`tookMs` 约几百毫秒。

---

## 六、运维备忘

- 重启 SearXNG：`cd /home/docker/searxng && docker compose restart`
- 换配置后结果异常 → 先 `docker exec searxng-redis redis-cli FLUSHALL`
- 旧配置留备份：`settings.yml.bak-keeponly`、`settings.yml.bak-engines`
- 登录 Control UI：`http://<host>:10084`（用户名 admin / 密码见部署方自定）

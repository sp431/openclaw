# sp431/openclaw

家庭内网 OpenClaw 实例的运维记录与可复用脚本。

## 目录

- [`web_search/`](./web_search/) — **基于自托管 SearXNG 为 OpenClaw 接入 web_search**
  - README.md：部署 + 接入 + 排查经验（完整）
  - settings.yml：SearXNG 配置（keep_only + 显式 disabled:false，含关键注释）
  - docker-compose.yml：SearXNG + Redis
  - deploy_searxng.py：一键部署/冒烟脚本（SSH 凭据走环境变量，脱敏）
  - openclaw_setup.txt：OpenClaw 侧命令清单

> 所有脚本均已脱敏：主机 IP、密码、Token 使用占位符或环境变量，请按需替换。

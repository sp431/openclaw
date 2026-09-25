#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
部署 SearXNG settings.yml 到远程主机并做冒烟测试（OpenClaw web_search 用）

用法：
  需要 paramiko 与 pyyaml：
    pip install paramiko pyyaml
  通过环境变量提供 SSH 凭据，避免明文入库：
    export TTY_HOST=192.168.x.x
    export TTY_USER=root
    export TTY_PASS='你的密码'
    python3 deploy_searxng.py

说明：
  - 本脚本将本地 web_search/settings.yml 上传到 <部署目录>/settings.yml
  - 先做 YAML 校验，再替换、清 Redis、重启容器、冒烟测试默认聚合搜索
  - 部署目录默认 /home/docker/searxng，可用 DEPLOY_DIR 覆盖
"""
import os
import json
import time

import paramiko

HOST = os.environ.get("TTY_HOST", "")
USER = os.environ.get("TTY_USER", "root")
PWD = os.environ.get("TTY_PASS", "")
DEPLOY_DIR = os.environ.get("DEPLOY_DIR", "/home/docker/searxng")
LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.yml")


def run(c, cmd, t=120):
    i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")


def main():
    if not (HOST and PWD):
        raise SystemExit("请设置环境变量 TTY_HOST / TTY_USER / TTY_PASS")
    data = open(LOCAL, "rb").read()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PWD, timeout=15,
              allow_agent=False, look_for_keys=False)

    # 备份旧配置
    out, err = run(c, f"cp -a {DEPLOY_DIR}/settings.yml {DEPLOY_DIR}/settings.yml.bak-$(date +%Y%m%d%H%M) && echo backed_up")
    print(out, err)

    # 上传到临时文件
    si, so, se = c.exec_command("cat > /tmp/settings.new.yml")
    si.write(data)
    si.channel.shutdown_write()
    print("upload rc", so.channel.recv_exit_status(), "bytes", len(data))

    # YAML 校验后替换
    out, err = run(c, f'''python3 -c "import yaml;d=yaml.safe_load(open('/tmp/settings.new.yml'));print('yaml OK engines=',len(d.get('engines',[])))" && cp /tmp/settings.new.yml {DEPLOY_DIR}/settings.yml && echo moved''')
    print(out, err)

    # 清 Redis + 重启
    run(c, "docker exec searxng-redis redis-cli FLUSHALL >/dev/null 2>&1")
    run(c, f"cd {DEPLOY_DIR} && docker compose up -d --force-recreate searxng >/dev/null 2>&1")
    print("wait 16s for startup...")
    time.sleep(16)

    # 冒烟：首页 + 默认聚合中文搜索
    out, err = run(c, "curl -s -o /dev/null -w 'home:%{http_code}\\n' http://127.0.0.1:8088/")
    print(out, err)
    out, err = run(c, "curl -s 'http://127.0.0.1:8088/search?q=%E5%8C%97%E4%BA%AC%E5%A4%A9%E6%B0%94&format=json' -H 'Accept: application/json'")
    try:
        d = json.loads(out)
        print("DEFAULT AGG results:", len(d["results"]),
              "unresponsive:", d["unresponsive_engines"])
    except Exception as ex:
        print("parse fail", ex, out[:300])
    c.close()


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
用 LLM 为数据里的每个仓库批量生成中文简介（它是干什么的、对 Agent 用户有什么具体作用），
写入 data/repos.json 的 intro 字段。

- 需要 config.json / config.local.json / 环境变量中配置 llm.api_key（默认 DeepSeek，兼容任何 OpenAI 接口）
- 没配置 key 时直接提示退出，不报错（供 Actions 里可选执行）
- 支持增量：已生成过介绍的仓库自动跳过

用法：
    python gen_intros.py                 # 为所有缺介绍的仓库生成
    python gen_intros.py --limit 50      # 本次最多生成 50 个（云端每日增量用）
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request

import fetcher

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BATCH_SIZE = 8
INTRO_MIN, INTRO_MAX = 12, 150

PROMPT = """你在为一个「Agent 工具雷达」项目给 GitHub 仓库撰写中文简介。这些仓库都是给 AI Agent（如 Claude、GPT、Cursor 等智能体）使用的工具：MCP 服务器、Agent Skill（技能包）、Agent 插件等。

对下面每个仓库，用中文写一段 40~90 字的简介，要求：
1. 第一句：说清楚这个仓库是干什么的（属于什么类型的工具、提供什么能力）；
2. 第二句：说清楚用户装了它之后，能让自己的 AI Agent 具体做到什么（举实际使用场景）；
3. 语气平实，不夸大不营销；如果描述信息不足，就根据名称和标签谨慎概括，不要编造具体功能细节。

只输出 JSON 对象（不要任何其他文字）：{"results":[{"full_name":"仓库全名","intro":"简介"}]}
列表里每个仓库都必须出现在 results 中，intro 用简体中文。

仓库列表：
{repos}"""


def chat(messages, cfg, timeout=90):
    base = (cfg.get("base_url") or "https://api.deepseek.com").rstrip("/")
    payload = {
        "model": cfg.get("model") or "deepseek-chat",
        "temperature": 0.7,
        "messages": messages,
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["api_key"]},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def parse_results(content):
    """容错解析 LLM 返回的 JSON（容忍 markdown 围栏、前后杂文字）。"""
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
    try:
        obj = json.loads(content)
    except Exception:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return None
    results = obj.get("results") if isinstance(obj, dict) else obj
    if not isinstance(results, list):
        return None
    out = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        name = str(item.get("full_name", "")).strip()
        intro = str(item.get("intro", "")).strip()
        if name and INTRO_MIN <= len(intro):
            out[name] = intro[:INTRO_MAX]
    return out or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="本次最多生成多少个（0=不限制）")
    args = ap.parse_args()

    cfg = fetcher.load_config()
    llm_cfg = cfg.get("llm", {})
    if not llm_cfg.get("api_key"):
        print("未配置 llm.api_key，跳过中文介绍生成。")
        print("配置方法：把 config.local.example.json 改名为 config.local.json 并填入 DeepSeek API Key，")
        print("或设置环境变量 DEEPSEEK_API_KEY（云端则在仓库 Secrets 里配置）。")
        return 0

    db = fetcher.load_db()
    targets = [r for r in db["repos"] if not r.get("intro") and r.get("full_name")]
    if args.limit and args.limit > 0:
        targets = targets[:args.limit]
    total_missing = sum(1 for r in db["repos"] if not r.get("intro") and r.get("full_name"))
    if not targets:
        print("所有仓库都已有中文介绍，无需生成。")
        return 0

    print("待生成介绍：%d 个（总缺 %d 个，本次限额 %s）"
          % (len(targets), total_missing, args.limit or "无"))
    updated = 0
    failed_batches = 0
    by_name = {r["full_name"]: r for r in db["repos"]}

    for i in range(0, len(targets), BATCH_SIZE):
        batch = targets[i:i + BATCH_SIZE]
        listing = "\n".join(
            "%d. %s — %s — topics: %s" % (
                j + 1, r["full_name"],
                (r.get("description") or "（无描述）")[:300],
                ", ".join((r.get("topics") or [])[:8]) or "无")
            for j, r in enumerate(batch))
        prompt = PROMPT.replace("{repos}", listing)
        content = None
        for attempt in (1, 2):
            try:
                content = chat(
                    [{"role": "system", "content": "你是严谨的技术编辑，只输出 JSON。"},
                     {"role": "user", "content": prompt}],
                    llm_cfg)
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt == 1:
                    wait = 25
                    try:
                        wait = min(int(e.headers.get("Retry-After", 25)) or 25, 120)
                    except Exception:
                        pass
                    print("  [批 %d] 接口限流/异常（HTTP %d），等待 %ds 重试..." % (i // BATCH_SIZE + 1, e.code, wait))
                    time.sleep(wait)
                else:
                    print("  [批 %d] 请求失败：HTTP %d" % (i // BATCH_SIZE + 1, e.code))
                    break
            except Exception as e:
                print("  [批 %d] 请求失败：%r" % (i // BATCH_SIZE + 1, e))
                break
        results = parse_results(content) if content else None
        if not results:
            failed_batches += 1
            print("  [批 %d] 解析失败，跳过（%s ...）" % (i // BATCH_SIZE + 1, batch[0]["full_name"]))
        else:
            for r in batch:
                intro = results.get(r["full_name"])
                if intro:
                    r["intro"] = intro
                    updated += 1
        print("进度：%d/%d，已生成 %d 条介绍" % (min(i + BATCH_SIZE, len(targets)), len(targets), updated))
        time.sleep(1.2)

    if updated:
        fetcher.save_db(db)
        print("完成：本次生成 %d 条中文介绍，已写入 %s" % (updated, fetcher.DATA_FILE))
    else:
        print("本次未能生成任何介绍（失败批次 %d）。" % failed_batches)
    if failed_batches:
        print("提示：个别批次失败不影响整体，重跑本脚本会自动补齐缺介绍的仓库。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

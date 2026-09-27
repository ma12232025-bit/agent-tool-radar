# -*- coding: utf-8 -*-
"""
GitHub 抓取器：定时搜索 GitHub 上高星的 Agent 工具仓库
（MCP 服务器 / Agent Skill / Agent 插件），结果存入 data/repos.json。

可独立运行（例如配合 Windows 计划任务每天自动跑一次）：
    python fetcher.py --once          # 完整扫描一次
    python fetcher.py --once --quick  # 快速扫描（少量查询，用于测试）
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(ROOT, "config.json")
DATA_DIR = os.path.join(ROOT, "data")
DATA_FILE = os.path.join(DATA_DIR, "repos.json")
MAX_REPOS = 4000

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # 环境变量优先（避免把 token 写进文件）
    cfg["github_token"] = (os.environ.get("GITHUB_TOKEN")
                           or os.environ.get("GH_TOKEN")
                           or cfg.get("github_token", ""))
    llm = cfg.setdefault("llm", {})
    llm["api_key"] = (os.environ.get("ZHIPUAI_API_KEY")
                      or os.environ.get("GLM_API_KEY")
                      or os.environ.get("OPENAI_API_KEY")
                      or llm.get("api_key", ""))
    return cfg


# 每条：(类别提示, GitHub 搜索语法)。类别提示仅用于日志展示。
SEARCH_QUERIES = [
    ("mcp",    "topic:mcp"),
    ("mcp",    "topic:model-context-protocol"),
    ("mcp",    "topic:mcp-server"),
    ("mcp",    '"MCP server" in:name,description'),
    ("mcp",    "mcp-server in:name"),
    ("skill",  "topic:claude-skills"),
    ("skill",  "topic:agent-skills"),
    ("skill",  '"agent skills" in:name,description'),
    ("skill",  "claude skill in:name,description"),
    ("plugin", "topic:claude-plugins"),
    ("plugin", "topic:claude-code"),
    ("plugin", "plugin marketplace claude in:name,description"),
    ("plugin", "agent plugin in:name,description"),
    ("awesome", '"awesome mcp" in:name,description'),
    ("awesome", '"awesome claude" in:name,description'),
]


class RateLimited(Exception):
    """GitHub 搜索接口限流，wait_seconds 为建议等待秒数。"""

    def __init__(self, wait_seconds):
        super().__init__("GitHub rate limited")
        self.wait_seconds = wait_seconds


def http_json(url, token, timeout=30):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "agent-tool-radar/1.0",
    })
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        headers = e.headers or {}
        if e.code in (403, 429):
            retry_after = headers.get("Retry-After")
            reset = headers.get("X-RateLimit-Reset")
            if retry_after:
                raise RateLimited(int(retry_after) + 2)
            if reset:
                raise RateLimited(max(1, int(reset) - int(time.time()) + 2))
        raise


def search_repos(query, token, per_page=30, timeout=30):
    """按 GitHub 仓库搜索语法查询，按星数降序。"""
    q = urllib.parse.quote(query + " fork:false", safe="")
    url = ("https://api.github.com/search/repositories?q=" + q +
           "&sort=stars&order=desc&per_page=" + str(per_page))
    return http_json(url, token, timeout=timeout)


AGENT_WORDS = ("agent", "claude", "gpt", "llm", "assistant", "copilot",
               "cursor", "openai", "anthropic", "mcp")


def classify(name, desc, topics):
    """根据名称/描述/topics 粗分类：mcp / skill / plugin / other（可多选）。"""
    topics_l = [t.lower() for t in (topics or [])]
    topic_str = " ".join(topics_l)
    text = (name + " " + (desc or "")).lower()
    cats = []
    if ("mcp" in topics_l or "model-context-protocol" in topics_l
            or re.search(r"\bmcp\b", text) or "model context protocol" in text):
        cats.append("mcp")
    if (any(t in ("skill", "skills", "claude-skills", "agent-skills",
                  "skill-library") for t in topics_l)
            or "skill.md" in text
            or ("skill" in text and any(w in text for w in AGENT_WORDS))):
        cats.append("skill")
    if ("plugin" in topic_str or "plugins" in topics_l
            or "claude-code" in topics_l
            or ("marketplace" in text and "claude" in text)
            or ("plugin" in text and any(w in text for w in AGENT_WORDS))):
        cats.append("plugin")
    return cats or ["other"]


def item_to_repo(item):
    return {
        "full_name": item.get("full_name", ""),
        "url": item.get("html_url", ""),
        "description": item.get("description") or "",
        "stars": int(item.get("stargazers_count") or 0),
        "language": item.get("language") or "",
        "topics": [t for t in (item.get("topics") or [])][:12],
        "pushed_at": (item.get("pushed_at") or "")[:10],
        "categories": classify(item.get("name") or "",
                               item.get("description") or "",
                               item.get("topics")),
    }


def load_db():
    if not os.path.exists(DATA_FILE):
        return {"meta": {"last_fetched": None, "last_fetched_ts": 0,
                         "last_summary": "", "last_error": None},
                "repos": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    os.makedirs(DATA_DIR, exist_ok=True)
    db["repos"].sort(key=lambda r: r.get("stars", 0), reverse=True)
    db["repos"] = db["repos"][:MAX_REPOS]
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)


def run_fetch(config, quick=False, log=print):
    """跑一轮完整扫描，返回 (新增数, 更新数, 收录总数)。"""
    token = config.get("github_token") or ""
    min_stars = int(config.get("min_stars", 20))
    per_query = int(config.get("search", {}).get("per_query_results", 30))
    queries = SEARCH_QUERIES[:6] if quick else SEARCH_QUERIES
    # 无 token 搜索限额 10 次/分钟，间隔 6.5s；有 token 30 次/分钟，间隔 2.5s
    gap = 2.5 if token else 6.5

    db = load_db()
    by_name = {r["full_name"].lower(): r for r in db["repos"]}
    added = updated = 0
    errors = []

    log("开始扫描 GitHub（%d 个查询，间隔 %.1fs）..." % (len(queries), gap))
    for i, (cat, query) in enumerate(queries):
        if i:
            time.sleep(gap)
        data = None
        for attempt in (1, 2):
            try:
                data = search_repos(query, token, per_page=per_query)
                break
            except RateLimited as e:
                wait = min(e.wait_seconds, 180)
                log("  触发限流，等待 %ds 后重试..." % wait)
                time.sleep(wait)
            except Exception as e:
                errors.append("%s: %s" % (query, e))
                log("  查询失败: %s" % e)
                break
        if data is None:
            continue
        for item in data.get("items", []):
            repo = item_to_repo(item)
            if repo["stars"] < min_stars:
                continue
            key = repo["full_name"].lower()
            if key in by_name:
                old = by_name[key]
                for k, v in repo.items():
                    if v:
                        old[k] = v
                updated += 1
            else:
                by_name[key] = repo
                db["repos"].append(repo)
                added += 1
        log("  [%d/%d] (%s) %s → 累计新增 %d" % (i + 1, len(queries), cat, query, added))

    db["meta"]["last_fetched"] = time.strftime("%Y-%m-%d %H:%M:%S")
    db["meta"]["last_fetched_ts"] = time.time()
    db["meta"]["last_summary"] = "新增 %d · 更新 %d · 收录 %d" % (added, updated, len(db["repos"]))
    db["meta"]["last_error"] = "；".join(errors) if errors else None
    save_db(db)
    log("扫描完成：%s" % db["meta"]["last_summary"])
    if errors:
        log("部分查询失败（不影响已获取数据）：%s" % db["meta"]["last_error"])
    return added, updated, len(db["repos"])


def main():
    ap = argparse.ArgumentParser(description="GitHub Agent 工具抓取器")
    ap.add_argument("--once", action="store_true", help="扫描一次后退出")
    ap.add_argument("--quick", action="store_true", help="快速模式（少量查询）")
    args = ap.parse_args()
    cfg = load_config()
    run_fetch(cfg, quick=args.quick)


if __name__ == "__main__":
    main()

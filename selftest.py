# -*- coding: utf-8 -*-
"""本地自检脚本：先启动服务（python app.py），再运行 python selftest.py。"""
import json
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8765"

try:
    sys.stdout.reconfigure(errors="replace")  # 跟随控制台编码，避免中文乱码
except Exception:
    pass


def get(path, **params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    stats = get("/api/stats")
    print("== 统计 ==")
    print("收录总数: %s | MCP: %s | Skill: %s | 插件: %s" % (
        stats["total"], stats["categories"]["mcp"], stats["categories"]["skill"],
        stats["categories"]["plugin"]))
    print("上次扫描: %s（%s）" % (stats["meta"]["last_fetched"], stats["meta"]["last_summary"]))
    print("下次扫描: %s | LLM 增强: %s" % (stats["next_fetch_human"], "已开启" if stats["llm_enabled"] else "未配置"))

    repos = get("/api/repos", category="mcp", min_stars=100, limit=5)
    print("\n== MCP 高星前 5 ==")
    for r in repos["repos"]:
        print("  ★%-7d %s — %s" % (r["stars"], r["full_name"], (r["description"] or "")[:60]))

    res = get("/api/search", q="自动处理 PDF 发票并汇总到 Excel 表格", live=1)
    print("\n== 中文需求搜索：“自动处理 PDF 发票并汇总到 Excel 表格” ==")
    print("结果 %d 个 | 实时新发现 %d 个 | %s%s" % (
        res["total"], res["fresh_added"], "LLM 增强" if res["llm_used"] else "词典匹配",
        (" | " + res["note"]) if res.get("note") else ""))
    for r in res["results"][:8]:
        print("  %-6s ★%-7d %s" % (r["score"], r["stars"], r["full_name"]))
        print("         匹配: %s" % ", ".join(r["matched"][:6]))

    print("\n自检通过 ✔")


if __name__ == "__main__":
    main()

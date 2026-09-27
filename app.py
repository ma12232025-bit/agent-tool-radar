# -*- coding: utf-8 -*-
"""
Agent 工具雷达 —— 本地 Web 服务 + 定时抓取调度器。

运行：python app.py
然后浏览器自动打开 http://localhost:8765

功能：
- 每隔 fetch_interval_hours 小时自动扫描一次 GitHub（后台线程）；
- GET  /api/stats          统计信息
- GET  /api/repos          浏览仓库（category / min_stars / q / offset）
- GET  /api/search         中文需求智能查找（q / live）
- POST /api/fetch          立即触发一次扫描
"""
import json
import os
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import fetcher
import search_engine

ROOT = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(ROOT, "web", "index.html")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line)
    if LOG_HANDLE:
        try:
            LOG_HANDLE[0].write(line + "\n")
            LOG_HANDLE[0].flush()
        except Exception:
            pass


CONFIG = fetcher.load_config()
DB_LOCK = threading.Lock()
LOG_HANDLE = []  # main() 启动后填入日志文件句柄
DB = fetcher.load_db()
DB_MTIME = os.path.getmtime(fetcher.DATA_FILE) if os.path.exists(fetcher.DATA_FILE) else 0
FETCH_STATE = {"running": False, "message": "", "last_done": None}
FRESH_NAMES = set()  # 本次会话中通过实时搜索新发现的仓库


def reload_db_if_changed():
    """数据文件被外部更新时（例如计划任务跑了 fetcher.py），自动重新载入。"""
    global DB, DB_MTIME
    if not os.path.exists(fetcher.DATA_FILE):
        return
    mtime = os.path.getmtime(fetcher.DATA_FILE)
    if mtime == DB_MTIME:
        return
    with DB_LOCK:
        DB = fetcher.load_db()
        DB_MTIME = mtime
    log("检测到数据文件已更新，已重新载入（共 %d 个仓库）" % len(DB.get("repos", [])))


def run_fetch_job():
    """后台线程跑一轮扫描，完成后重载数据。"""
    if FETCH_STATE["running"]:
        return False
    FETCH_STATE["running"] = True
    FETCH_STATE["message"] = "正在扫描 GitHub ..."

    def work():
        global DB
        try:
            added, updated, total = fetcher.run_fetch(CONFIG, log=log)
            FETCH_STATE["message"] = "扫描完成：新增 %d · 更新 %d · 共收录 %d" % (added, updated, total)
        except Exception as e:
            FETCH_STATE["message"] = "扫描失败：%r" % e
            log("抓取失败: %r" % e)
        finally:
            with DB_LOCK:
                DB = fetcher.load_db()
                if os.path.exists(fetcher.DATA_FILE):
                    DB_MTIME = os.path.getmtime(fetcher.DATA_FILE)
            FETCH_STATE["running"] = False
            FETCH_STATE["last_done"] = time.time()

    threading.Thread(target=work, daemon=True).start()
    return True


def scheduler_loop():
    interval = max(0.05, float(CONFIG.get("fetch_interval_hours", 24))) * 3600
    while True:
        try:
            last = DB.get("meta", {}).get("last_fetched_ts") or 0
            if time.time() - last >= interval:
                log("定时任务触发（每 %.1f 小时一次）" % (interval / 3600))
                run_fetch_job()
        except Exception as e:
            log("调度器异常: %r" % e)
        time.sleep(60)


def merge_live_results(items):
    """把实时搜索到的仓库合并进本地库（允许低星），返回 (新增数, 新增名单)。"""
    global DB_MTIME
    added = 0
    new_names = []
    with DB_LOCK:
        by_name = {r["full_name"].lower(): r for r in DB["repos"]}
        for item in items:
            repo = fetcher.item_to_repo(item)
            if not repo["full_name"] or repo["stars"] < 1:
                continue
            key = repo["full_name"].lower()
            if key not in by_name:
                by_name[key] = repo
                DB["repos"].append(repo)
                added += 1
                new_names.append(repo["full_name"])
            else:
                old = by_name[key]
                for k, v in repo.items():
                    if v:
                        old[k] = v
        if added:
            fetcher.save_db(DB)
            if os.path.exists(fetcher.DATA_FILE):
                DB_MTIME = os.path.getmtime(fetcher.DATA_FILE)
    return added, new_names


def api_browse(args):
    reload_db_if_changed()
    category = args.get("category", ["all"])[0]
    q = (args.get("q", [""])[0] or "").strip().lower()
    min_stars = int(args.get("min_stars", ["0"])[0] or 0)
    limit = min(100, int(args.get("limit", ["30"])[0] or 30))
    offset = max(0, int(args.get("offset", ["0"])[0] or 0))
    with DB_LOCK:
        repos = list(DB.get("repos", []))
    out = []
    for r in repos:
        if category != "all" and category not in r.get("categories", []):
            continue
        if r.get("stars", 0) < min_stars:
            continue
        if q:
            hay = (r.get("full_name", "") + " " + (r.get("description") or "")
                   + " " + " ".join(r.get("topics") or [])).lower()
            if q not in hay:
                continue
        out.append(r)
    out.sort(key=lambda r: r.get("stars", 0), reverse=True)
    return {"total": len(out), "offset": offset, "repos": out[offset:offset + limit]}


def api_search(args):
    reload_db_if_changed()
    text = (args.get("q", [""])[0] or "").strip()
    if not text:
        return {"error": "缺少参数 q（用中文描述你的需求）"}
    live_cfg = CONFIG.get("search", {})
    live = (args.get("live", ["1"])[0] != "0") and bool(live_cfg.get("live_search_on_query", True))
    llm_cfg = CONFIG.get("llm", {})

    with DB_LOCK:
        repos = list(DB.get("repos", []))
    result = search_engine.search(repos, text, llm_cfg)

    fresh_added = 0
    if live:
        token = CONFIG.get("github_token") or ""
        queries = result.get("llm_queries", [])[:2] if result.get("llm_used") else []
        if not queries:
            top = sorted(result.get("keywords", {}).items(), key=lambda kv: kv[1], reverse=True)
            kws = [k for k, _ in top[:4]]
            if kws:
                queries = ["(%s) (mcp OR agent OR claude)" % " OR ".join(kws)]
        for query in queries:
            try:
                log("实时搜索: %s" % query)
                data = fetcher.search_repos(query, token,
                                            per_page=int(live_cfg.get("live_results_per_query", 15)))
                n, names = merge_live_results(data.get("items", []))
                fresh_added += n
                FRESH_NAMES.update(names)
                time.sleep(1.5)
            except Exception as e:
                log("实时搜索失败 %s: %r" % (query, e))
        if fresh_added:
            with DB_LOCK:
                repos = list(DB.get("repos", []))
            result = search_engine.search(repos, text, llm_cfg)

    result.pop("keywords", None)  # 关键词表太大，仅保留 matched
    result["fresh_added"] = fresh_added
    for r in result["results"]:
        r["fresh"] = r.get("full_name") in FRESH_NAMES
    result["query"] = text
    return result


def api_stats():
    reload_db_if_changed()
    with DB_LOCK:
        repos = list(DB.get("repos", []))
        meta = dict(DB.get("meta", {}))
    cats = {"mcp": 0, "skill": 0, "plugin": 0, "other": 0}
    for r in repos:
        for c in r.get("categories", []):
            if c in cats:
                cats[c] += 1
    interval = float(CONFIG.get("fetch_interval_hours", 24))
    next_ts = (meta.get("last_fetched_ts") or 0) + interval * 3600
    return {
        "total": len(repos),
        "categories": cats,
        "meta": {"last_fetched": meta.get("last_fetched"),
                 "last_summary": meta.get("last_summary"),
                 "last_error": meta.get("last_error")},
        "interval_hours": interval,
        "next_fetch_human": time.strftime("%Y-%m-%d %H:%M", time.localtime(next_ts)) if meta.get("last_fetched_ts") else "待首次扫描",
        "fetch_running": FETCH_STATE["running"],
        "fetch_message": FETCH_STATE["message"],
        "llm_enabled": bool(CONFIG.get("llm", {}).get("api_key")),
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # 静默访问日志

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except ConnectionAbortedError:
            pass

    def _route_get(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        args = urllib.parse.parse_qs(parsed.query)
        if route in ("/", "/index.html", "/index"):
            with open(INDEX_FILE, "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif route == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        elif route == "/api/stats":
            self._send(200, api_stats())
        elif route == "/api/repos":
            self._send(200, api_browse(args))
        elif route == "/api/search":
            self._send(200, api_search(args))
        elif route == "/api/fetch/status":
            self._send(200, {"running": FETCH_STATE["running"], "message": FETCH_STATE["message"]})
        else:
            self._send(404, {"error": "not found"})

    def do_GET(self):
        try:
            self._route_get()
        except BrokenPipeError:
            pass
        except Exception as e:
            log("GET %s 出错: %r" % (self.path, e))
            try:
                self._send(500, {"error": repr(e)})
            except Exception:
                pass

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path == "/api/fetch":
            started = run_fetch_job()
            self._send(200, {"started": started, "message": FETCH_STATE["message"]})
        else:
            self._send(404, {"error": "not found"})


def main():
    port = int(CONFIG.get("port", 8765))
    url = "http://localhost:%d" % port
    os.makedirs(os.path.dirname(fetcher.DATA_FILE), exist_ok=True)
    try:
        LOG_HANDLE.append(open(os.path.join(os.path.dirname(fetcher.DATA_FILE), "service.log"),
                               "a", encoding="utf-8"))
        LOG_HANDLE[0].write("\n===== %s 启动 =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        LOG_HANDLE[0].flush()
    except Exception:
        pass
    threading.Thread(target=scheduler_loop, daemon=True).start()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        print("端口 %d 已被占用：服务可能已经在运行。" % port)
        print("直接在浏览器打开 %s 即可。" % url)
        if CONFIG.get("open_browser", True):
            webbrowser.open(url)
        sys.exit(0)
    log("Agent 工具雷达已启动：%s" % url)
    log("数据文件：%s（当前收录 %d 个仓库）" % (fetcher.DATA_FILE, len(DB.get("repos", []))))
    log("定时扫描：每 %s 小时一次；按 Ctrl+C 停止。" % CONFIG.get("fetch_interval_hours", 24))
    if CONFIG.get("open_browser", True):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("已停止。")


if __name__ == "__main__":
    main()

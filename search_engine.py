# -*- coding: utf-8 -*-
"""
中文需求 → 英文关键词 → 仓库相关性匹配。

两层策略：
1. 内置领域词典：把中文说法映射成英文检索词（无需联网、无需 API Key）。
2. 可选 LLM 增强：若配置了兼容 OpenAI 接口的大模型 API（默认智谱 GLM），
   由 LLM 生成更精准的英文关键词和 GitHub 查询词。
"""
import json
import re
import urllib.request

# (中文触发词列表, 英文关键词列表, 权重)。权重越高越重要。
DOMAIN_MAP = [
    (["浏览器", "网页", "上网", "打开网站", "页面操作", "自动点击", "网页自动化", "截屏网页", "登录网站"],
     ["browser", "playwright", "puppeteer", "browser-use", "web", "scraping", "crawl", "headless", "chrome"], 3.0),
    (["搜索", "联网", "查资料", "查一下", "最新信息", "实时信息", "检索", "查询资料"],
     ["search", "web-search", "brave", "google", "bing", "tavily", "exa", "perplexity", "duckduckgo"], 3.0),
    (["爬虫", "抓取", "采集", "扒数据"],
     ["scraping", "crawler", "spider", "scraper", "fetch", "extract"], 3.0),
    (["pdf"], ["pdf"], 3.5),
    (["word", "docx", "公文", "文档生成"],
     ["docx", "word", "document", "office"], 2.8),
    (["excel", "表格", "电子表格", "csv", "汇总表"],
     ["excel", "spreadsheet", "csv", "xlsx", "sheet"], 3.2),
    (["ppt", "演示", "幻灯片", "slides"],
     ["ppt", "powerpoint", "slides", "presentation", "slidev"], 3.0),
    (["数据库", "sql", "建表", "查询数据", "数据表"],
     ["database", "sql", "postgres", "mysql", "sqlite", "supabase", "mongodb", "redis"], 3.0),
    (["图像", "图片", "画图", "绘图", "生图", "作图", "设计图", "海报", "配图"],
     ["image", "draw", "svg", "diagram", "design", "canvas", "figure", "illustration"], 2.8),
    (["图表", "可视化", "数据图", "报表", "架构图", "流程图"],
     ["chart", "visualization", "plot", "graph", "mermaid", "dashboard", "diagram"], 3.0),
    (["代码", "编程", "开发", "写程序", "重构", "调试", "脚本"],
     ["code", "coding", "dev", "refactor", "debug", "sdk", "cli"], 2.2),
    (["git", "github", "提交代码", "代码仓库", "代码审查"],
     ["git", "github", "pull-request", "issue", "repo", "commit", "code-review"], 3.2),
    (["翻译", "多语言", "译成", "中英"],
     ["translate", "translation", "language", "i18n"], 3.2),
    (["写作", "文案", "润色", "写文章", "博客", "公众号", "软文"],
     ["writing", "write", "content", "blog", "copywriting", "seo"], 2.6),
    (["邮件", "发邮件", "邮箱", "收件"],
     ["email", "gmail", "mail", "smtp", "imap"], 3.2),
    (["日历", "日程", "约会", "排期"],
     ["calendar", "schedule", "google-calendar"], 3.0),
    (["会议", "纪要", "会议记录", "会记", "速记"],
     ["meeting", "minutes", "transcri", "meeting-notes"], 2.8),
    (["提醒", "待办", "todo", "任务管理", "项目管理", "清单"],
     ["todo", "task", "reminder", "todoist", "linear", "jira", "asana", "ticktick"], 3.0),
    (["微信", "企业微信", "weixin"], ["wechat", "wecom"], 3.5),
    (["飞书", "lark"], ["feishu", "lark"], 3.5),
    (["钉钉"], ["dingtalk"], 3.5),
    (["slack"], ["slack"], 3.5),
    (["discord"], ["discord"], 3.5),
    (["telegram", "电报"], ["telegram"], 3.5),
    (["知识库", "笔记", "记忆", "记住", "rag", "向量", "embedding", "obsidian", "notion", "语雀"],
     ["memory", "knowledge", "rag", "notes", "obsidian", "notion", "vector", "embedding", "markdown"], 3.0),
    (["文件", "文件夹", "本地文件", "整理文件", "重命名"],
     ["filesystem", "file", "directory", "folder", "local"], 2.6),
    (["终端", "命令行", "shell", "执行命令", "跑命令"],
     ["terminal", "shell", "cli", "command", "exec", "bash"], 3.0),
    (["大模型", "llm", "gpt", "claude", "openai", "提示词", "prompt", "智能体", "agent", "聊天机器人"],
     ["llm", "openai", "anthropic", "gpt", "claude", "agent", "prompt", "ollama", "chatbot"], 2.4),
    (["语音", "朗读", "转文字", "语音识别", "tts", "asr", "录音", "播客"],
     ["voice", "speech", "tts", "asr", "audio", "whisper", "transcri"], 3.0),
    (["视频", "剪辑", "字幕", "b站", "bilibili", "youtube", "抖音", "短视频"],
     ["video", "youtube", "ffmpeg", "subtitle", "bilibili", "douyin", "clip"], 3.0),
    (["音乐", "spotify", "听歌"],
     ["music", "spotify", "audio", "song"], 3.0),
    (["金融", "股票", "基金", "加密", "比特币", "炒币", "行情", "交易", "汇率"],
     ["finance", "stock", "crypto", "bitcoin", "trading", "market", "binance"], 3.0),
    (["天气", "气温", "下雨"],
     ["weather"], 3.5),
    (["地图", "导航", "位置", "经纬度", "周边", "定位"],
     ["map", "location", "geo", "google-maps", "amap", "baidu-map"], 3.2),
    (["旅行", "机票", "酒店", "旅游", "行程", "攻略"],
     ["travel", "flight", "hotel", "booking", "trip", "airbnb"], 3.0),
    (["购物", "电商", "商品", "比价", "淘宝", "京东", "亚马逊", "网购"],
     ["shopping", "e-commerce", "amazon", "product", "taobao", "jd"], 2.8),
    (["新闻", "资讯", "头条", "rss", "订阅", "早报", "日报"],
     ["news", "rss", "hackernews", "feed", "digest"], 3.0),
    (["社交", "推特", "twitter", "微博", "reddit", "小红书"],
     ["twitter", "social", "reddit", "weibo"], 3.0),
    (["测试", "自动化测试", "qa", "单元测试", "用例"],
     ["test", "testing", "qa", "unit-test", "e2e", "pytest"], 3.0),
    (["部署", "运维", "devops", "docker", "k8s", "kubernetes", "上线", "服务器", "nginx"],
     ["docker", "kubernetes", "deploy", "devops", "cd", "infra", "terraform", "ssh", "k8s"], 3.0),
    (["监控", "日志", "报错监控", "observability", "告警"],
     ["monitoring", "logging", "observability", "sentry", "grafana", "alert"], 3.0),
    (["云服务", "aws", "阿里云", "腾讯云", "s3", "azure", "云计算", "云函数"],
     ["aws", "cloud", "azure", "gcp", "aliyun", "s3", "cloudflare"], 3.0),
    (["安全", "漏洞", "渗透", "扫描漏洞", "加固"],
     ["security", "pentest", "vulnerability", "scan", "cve"], 3.0),
    (["游戏", "3d", "unity", "blender", "建模", "渲染"],
     ["game", "3d", "unity", "blender", "three", "model"], 2.8),
    (["论文", "学术", "文献", "科研", "arxiv", "查文献", "文献综述"],
     ["arxiv", "paper", "research", "academic", "scholar", "pubmed", "citation"], 3.4),
    (["医疗", "健康", "看病", "药物", "症状"],
     ["health", "medical", "pubmed", "drug"], 2.8),
    (["数学", "计算", "算式", "方程", "解题", "公式"],
     ["math", "calculate", "wolfram", "sympy", "solver"], 3.0),
    (["ocr", "识别文字", "提取文字", "图片转文字", "识别图片"],
     ["ocr", "vision", "image-to-text", "recognize"], 3.4),
    (["二维码", "条形码", "qr"],
     ["qr", "barcode", "qrcode"], 3.5),
    (["时间", "日期", "时区", "几点", "倒计时"],
     ["time", "date", "timezone", "datetime"], 3.0),
    (["自动化", "工作流", "rpa", "效率", "批量处理", "流程", "自动运行"],
     ["automation", "workflow", "rpa", "n8n", "zapier", "script", "batch"], 2.6),
    (["安卓", "android", "手机", "ios", "iphone", "移动端"],
     ["android", "ios", "mobile", "adb"], 3.2),
    (["windows", "电脑操作", "桌面", "操作系统", "截屏"],
     ["windows", "desktop", "screenshot", "computer-use", "os"], 3.0),
    (["客服", "对话", "问答机器人"],
     ["chat", "chatbot", "conversation", "customer"], 2.2),
    (["简历", "招聘", "面试"], ["resume", "recruit", "interview", "linkedin"], 3.0),
    (["儿童", "教育", "教学", "学习", "老师"],
     ["education", "teaching", "learning", "tutor", "flashcard"], 2.6),
]

LLM_PROMPT = """用户正在使用一个"GitHub Agent 工具雷达"，想根据需求找到合适的 Agent 工具（MCP 服务器 / Agent Skill / Agent 插件）。
用户需求（中文）：{text}

请输出 JSON（不要输出任何其他内容）：
{{"keywords": ["5-12个与需求最相关的英文搜索关键词，小写，单词或短语"], "queries": ["1-3个适合在 GitHub 搜索相关仓库的英文查询词"]}}"""


def _llm_extract(text, llm_cfg):
    base = (llm_cfg.get("base_url") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
    model = llm_cfg.get("model") or "glm-4-flash"
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "你是一个搜索关键词生成器，只输出 JSON。"},
            {"role": "user", "content": LLM_PROMPT.format(text=text)},
        ],
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + llm_cfg["api_key"]},
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
    obj = json.loads(content)
    kws = [str(k).strip().lower() for k in obj.get("keywords", []) if str(k).strip()][:12]
    queries = [str(q).strip() for q in obj.get("queries", []) if str(q).strip()][:3]
    return kws, queries


def extract_keywords(text, llm_cfg):
    """返回 (关键词权重表, 是否用了LLM, 提示信息, LLM生成的GitHub查询词)。"""
    lowered = (text or "").lower()
    weights = {}

    def add(kw, w):
        kw = kw.strip().lower()
        if len(kw) < 2:
            return
        if kw not in weights or weights[kw] < w:
            weights[kw] = w

    for patterns, keywords, weight in DOMAIN_MAP:
        if any(p in lowered for p in patterns):
            for k in keywords:
                add(k, weight)
    # 用户输入里自带的英文单词也作为关键词
    for tok in re.findall(r"[a-z][a-z0-9_\-]{2,}", lowered):
        add(tok, 2.2)

    note = ""
    llm_queries = []
    llm_used = False
    if llm_cfg and llm_cfg.get("api_key"):
        try:
            llm_kws, llm_queries = _llm_extract(text, llm_cfg)
            llm_used = True
            for k in llm_kws:
                add(k, 3.2)
        except Exception as e:
            note = "LLM 关键词提取失败，已使用内置词典（%s）" % e
    return weights, llm_used, note, llm_queries


def score_repo(repo, kw_weights):
    """单个仓库与关键词的匹配打分：命中名称权重最高，topics 次之，描述最低。"""
    name = repo.get("full_name", "").lower()
    topics = " ".join(repo.get("topics") or []).lower()
    desc = (repo.get("description") or "").lower()
    total = 0.0
    matched = []
    strong_hit = False  # 名称或标签里命中，才算"主题对得上"
    for kw, w in kw_weights.items():
        s = 0.0
        if kw in name:
            s += 5 * w
            strong_hit = True
        if kw in topics:
            s += 4 * w
            strong_hit = True
        if kw in desc:
            s += 2.5 * w
        if s > 0:
            total += s
            matched.append(kw)
    # 只在描述里蹭到关键词的仓库（往往是泛泛提及）降低权重，减少噪音
    if matched and not strong_hit:
        total *= 0.5
    # 命中关键词越多说明需求匹配越全面，给一点加成
    if len(matched) >= 2:
        total *= 1.15
    return total, matched[:8]


def search(repos, text, llm_cfg, top_n=40):
    """在本地仓库库中按中文需求查找，返回排序后的结果。"""
    kw_weights, llm_used, note, llm_queries = extract_keywords(text, llm_cfg)
    scored = []
    for repo in repos:
        s, matched = score_repo(repo, kw_weights)
        if s > 0:
            scored.append((s, repo, matched))
    scored.sort(key=lambda t: (t[0], t[1].get("stars", 0)), reverse=True)
    results = []
    for s, repo, matched in scored[:top_n]:
        item = dict(repo)
        item["score"] = round(s, 2)
        item["matched"] = matched
        results.append(item)
    return {"keywords": kw_weights, "llm_used": llm_used, "note": note,
            "llm_queries": llm_queries, "total": len(results), "results": results}

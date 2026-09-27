# 🛰️ Agent 工具雷达（Agent Tool Radar）

一个**零依赖、纯本地运行**的小软件：自动定时扫描 GitHub，收录高星的
**Agent Skill（智能体技能）/ 插件（Plugin）/ MCP 服务器**，
并支持**用中文描述需求**，直接帮你找出最匹配的工具。

适用于任何 Agent 生态（Claude、GPT/OpenAI、Cursor、Copilot、通用 Agent 框架等）。

---

## 在线网页版（无需安装）

👉 **https://ma12232025-bit.github.io/agent-tool-radar/**

网页版是纯静态页面，打开即用：

- 中文需求查找与分类浏览的数据来自仓库内 `docs/data/repos.json`，
  由 GitHub Actions **每天上午 9:30（北京时间）在云端自动扫描更新**；
- 也支持在浏览器里**实时搜索 GitHub** 最新项目（走你自己的浏览器访问 GitHub，
  受匿名限额：每分钟 10 次左右）；
- 完整功能（本地数据库持续积累、LLM 智能增强、不受网页限额影响）请下载本仓库运行本地版。

### 部署你自己的实例

1. Fork 本仓库（或复制代码到你自己的仓库）；
2. 仓库 **Settings → Pages → Build and deployment → Source** 选 `Deploy from a branch`，
   分支选 `main`、目录选 `/docs`，保存；
3. 在 **Actions** 页确认「每日自动扫描 GitHub」工作流已启用（Fork 后需手动点一次 Enable）。

## 快速开始

1. 双击 **`start.bat`**（或命令行运行 `python app.py`）。
2. 浏览器会自动打开 `http://localhost:8765`。
3. 首次运行数据为空，点击右上角 **「⟳ 立即扫描」**，约 1–2 分钟即可收录数百个高星仓库。
   （之后每次启动会使用本地已保存的数据，不再重复扫描。）

## 两种用法

### ① 中文需求查找（核心功能）
在搜索框里用中文描述你要做的事，例如：

- “我想让 AI 自动读取 PDF 发票并汇总到 Excel”
- “需要一个能操作浏览器、自动填表截图的 MCP 工具”
- “帮我找写技术文档、画架构图相关的 skill”
- “想让智能体记住我的项目背景和长期记忆”

软件会自动把中文需求翻译成英文关键词（内置 50+ 领域词典；
配置了 LLM API Key 后走大模型更精准），在收录的仓库里按相关度 + 星数排序推荐，
并可**同时到 GitHub 实时搜索**最新项目（勾选框控制）。

### ② 按类别 / 星数浏览
用页签切换 **全部 / MCP 服务器 / Skills / 插件**，配合最低星数筛选
（默认 500+），浏览当前 GitHub 上最热门的 Agent 工具。

## 定时扫描机制（自动更新）

- **软件运行期间**：内置调度器每 `fetch_interval_hours`（默认 24）小时自动扫描一次，
  无需任何操作。
- **软件没开也能更新**：双击 **`install_task.bat`** 创建 Windows 计划任务
  （每天 09:10 运行 `update.bat` 抓一次），删除用：
  `schtasks /Delete /TN "AgentToolRadar-DailyFetch" /F`。
- **云端定时（推荐）**：仓库内置 `.github/workflows/update-data.yml`，
  GitHub Actions 每天 UTC 01:30（北京时间 09:30）自动扫描一次并提交更新，
  网页版与拉取代码的人都能拿到最新数据。

数据保存在 `data/repos.json`，可随时备份/迁移。

顺便一提：即使不开着软件，双击 `update.bat` 也能手动更新一次数据；
软件运行中若检测到数据文件被计划任务更新过，网页会自动读取新数据，无需重启。

## 配置（config.json）

| 字段 | 说明 |
|---|---|
| `port` | 网页端口，默认 8765 |
| `github_token` | 可选。GitHub Personal Access Token（不需要任何勾选权限）。不填也能用（约 10 次搜索/分钟），填了更快（30 次/分钟）。也可用环境变量 `GITHUB_TOKEN` |
| `fetch_interval_hours` | 自动扫描间隔（小时），默认 24 |
| `min_stars` | 扫描时收录的最低星数门槛，默认 20 |
| `open_browser` | 启动时是否自动打开浏览器 |
| `search.live_search_on_query` | 搜索时是否默认同时实时搜 GitHub |
| `llm.api_key` | 可选。填写后走 **LLM 智能匹配**（中英翻译、关键词、GitHub 查询词都由大模型生成），推荐填写。支持任何 OpenAI 兼容接口，默认指向智谱 `open.bigmodel.cn`（如 `glm-4-flash`），也可用环境变量 `ZHIPUAI_API_KEY` / `OPENAI_API_KEY` |
| `llm.base_url` / `llm.model` | LLM 接口地址与模型名，可换成 DeepSeek、通义、OpenAI 等 |

> 不配 LLM 也完全可用：内置词典覆盖浏览器、PDF/Office、数据库、图片图表、
> 爬虫、翻译写作、邮件日程、聊天平台（微信/飞书/钉钉/Slack…）、知识库记忆、
> 金融行情、论文科研、部署运维等常见领域。

## 文件结构

```
agent-tool-radar/
├── app.py            # 主程序：Web 服务 + 定时调度
├── fetcher.py        # GitHub 抓取器（可单独跑：python fetcher.py --once）
├── search_engine.py  # 中文需求 → 关键词 → 相关性匹配
├── build_web.py      # 生成 GitHub Pages 网页版静态数据
├── selftest.py       # 自检脚本（启动服务后运行 python selftest.py）
├── config.json       # 配置文件
├── web/index.html    # 本地网页界面
├── docs/             # GitHub Pages 网页版（纯静态，含 data/*.json）
├── .github/workflows/update-data.yml  # 每日云端自动扫描
├── start.bat         # 一键启动
├── update.bat        # 供计划任务调用：抓取一次并写日志
├── install_task.bat  # 创建每天自动更新的 Windows 计划任务
├── data/repos.json   # 抓取结果（自动生成）
└── data/service.log  # 运行日志（自动生成，排查问题用）
```

## 常见问题

- **扫描时部分查询失败 / 403**：GitHub 匿名搜索限流（10 次/分钟），软件会自动等待重试；
  配置 `github_token` 后基本不会再出现。
- **搜索结果太少**：多写几个关键词（中英文混写也行，如 “PDF 发票 invoice”）；
  或勾选“实时搜索”；或配置 LLM API Key。
- **端口被占用**：改 `config.json` 里的 `port`；若提示 8765 已被占用，
  说明软件已在运行，直接打开 http://localhost:8765 即可。
- **数据能存多少**：最多收录 4000 个仓库（按星数保留）。

## 说明与免责

数据来自 GitHub 公开 Search API，本工具仅作发现与导航；
安装、使用任何第三方 Skill / 插件 / MCP 前，请自行审查其代码与许可协议，注意安全。

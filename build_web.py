# -*- coding: utf-8 -*-
"""生成网页版（GitHub Pages）所需的静态数据：
- docs/data/repos.json    抓取到的仓库数据（含 meta）
- docs/data/keywords.json 中文领域词典（前端打分用）

本地运行：python build_web.py
GitHub Actions 每日抓取后也会调用本脚本更新网页版数据。
"""
import json
import os

import fetcher
import search_engine

ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS_DATA = os.path.join(ROOT, "docs", "data")


def main():
    os.makedirs(DOCS_DATA, exist_ok=True)
    db = fetcher.load_db()
    with open(os.path.join(DOCS_DATA, "repos.json"), "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False)
    with open(os.path.join(DOCS_DATA, "keywords.json"), "w", encoding="utf-8") as f:
        json.dump(search_engine.DOMAIN_MAP, f, ensure_ascii=False)
    print("网页版数据已生成：%d 个仓库，%d 组关键词，上次扫描 %s"
          % (len(db.get("repos", [])), len(search_engine.DOMAIN_MAP),
             db.get("meta", {}).get("last_fetched")))


if __name__ == "__main__":
    main()

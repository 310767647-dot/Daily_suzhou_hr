#!/usr/bin/env python3
"""
苏州人社 · 每日信息速递
=========================
功能：
  1. 每天收集苏州人力资源和社会保障局官网相关信息
  2. 搜狗微信搜索补充公众号文章
  3. 智能过滤 AI / 技能培训 / 创新创业 等关键词内容
  4. 通过飞书 Webhook 推送消息卡片到群
  5. 内置去重缓存，避免重复推送

定时方式：cron-job.org → GitHub API → GitHub Actions workflow_dispatch

参考：Daily_science 程序架构
"""

import json
import os
import re
import datetime
import hashlib
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ── 路径 ──
PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = OUTPUT_DIR / ".sent_cache.json"

# ── 飞书 Webhook（从环境变量读取，优先使用）──
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK") or \
    "https://open.feishu.cn/open-apis/bot/v2/hook/5a31043e-5ed0-4199-a4c3-7c57490f4d49"

# ── 网站配置 ──
BASE_URL = "http://hrss.suzhou.gov.cn"

# 监控栏目配置（名称, 列表页URL, 文章链接前缀, 分类标签）
SECTIONS = [
    # ── 苏州人社局 ──
    {
        "name": "人社要闻",
        "list_url": "http://hrss.suzhou.gov.cn/jsszhrss/zxdt/list.shtml",
        "link_prefix": "/jsszhrss/zxdt/",
        "icon": "📰",
    },
    {
        "name": "通知公告",
        "list_url": "http://hrss.suzhou.gov.cn/jsszhrss/gsgg/list.shtml",
        "link_prefix": "/jsszhrss/gsgg/",
        "icon": "📢",
    },
    {
        "name": "区县动态",
        "list_url": "http://hrss.suzhou.gov.cn/jsszhrss/qxdt/list.shtml",
        "link_prefix": "/jsszhrss/qxdt/",
        "icon": "🏘️",
    },
    {
        "name": "就业创业",
        "list_url": "http://hrss.suzhou.gov.cn/jsszhrss/jypx/lists.shtml",
        "link_prefix": "/jsszhrss/jypx/",
        "icon": "💼",
    },
    {
        "name": "人才人事",
        "list_url": "http://hrss.suzhou.gov.cn/jsszhrss/rsgl/list.shtml",
        "link_prefix": "/jsszhrss/rsgl/",
        "icon": "👥",
    },
    # ── 苏州工信局 ──
    {
        "name": "工信动态",
        "list_url": "http://gxj.suzhou.gov.cn/szeic/szgxdt/common_list.shtml",
        "link_prefix": "/szeic/szgxdt/",
        "icon": "🏭",
    },
    {
        "name": "新闻动态",
        "list_url": "http://gxj.suzhou.gov.cn/szeic/xwdt/xwzx.shtml",
        "link_prefix": "/szeic/xwdt/",
        "icon": "📡",
    },
]

# ── AI / 技能培训 关键词 ──
AI_KEYWORDS = [
    "人工智能", "AI", "ai", "大模型", "机器学习", "深度学习",
    "神经网络", "自然语言", "计算机视觉", "智能", "算法",
    "数据挖掘", "数据分析", "大数据", "云计算", "数字化",
    "信息化", "自动化", "机器人", "人形机器人", "无人机",
    "编程", "代码", "软件", "互联网+", "区块链", "物联网",
    "5G", "6G", "芯片", "半导体",
    # 工信领域拓展
    "工业互联网", "智能制造", "集成电路", "RISC-V",
    "新能源", "智能网联", "新能源汽车", "产业链",
    "绿色制造", "产业创新", "新型工业化", "先进制造",
    "专精特新", "数字经济", "信创", "软件产业",
]

SKILLS_KEYWORDS = [
    "培训", "技能", "夜校", "课程", "学习", "讲座",
    "大赛", "竞赛", "比赛", "竞技", "状元",
    "创新", "创业", "创赢", "孵化",
    "人才", "紧缺人才", "高层次人才", "留学人才",
    "就业", "招聘", "双选", "见习", "实训",
    "职业技能", "职业资格", "职称", "技能等级",
    "技术", "工艺", "工匠",
    # 工信领域拓展
    "对接会", "推进会", "交流会", "宣讲会",
    "产业集群", "产业链", "生态", "赋能",
]

# 组合为完整关键词列表
ALL_KEYWORDS = AI_KEYWORDS + SKILLS_KEYWORDS

# 排除关键词（明显不相关）
EXCLUDE_KEYWORDS = [
    "退休", "养老金", "丧葬", "抚恤", "工伤认定",
    "劳动监察", "仲裁", "投诉",
]


# ═══════════════════════════════════════════
#  缓存管理（已推送去重）
# ═══════════════════════════════════════════
def load_cache():
    """加载已推送文章的缓存（文章URL的SHA256集合）"""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, ValueError):
            pass
    return set()


def save_cache(cache):
    """保存缓存到文件，最多保留500条"""
    limited = set(list(cache)[-500:])    # 控制缓存大小
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(limited), f, ensure_ascii=False)


def make_key(url, title):
    """生成文章唯一标识"""
    raw = f"{url}|{title[:30]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════
#  网页抓取模块
# ═══════════════════════════════════════════

def fetch_page(url, timeout=15):
    """通用抓取函数"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.encoding = "utf-8"
        if resp.status_code == 200:
            return resp.text
        else:
            print(f"  ⚠️ HTTP {resp.status_code}: {url}")
            return ""
    except requests.RequestException as e:
        print(f"  ⚠️ 请求失败: {url} — {e}")
        return ""


def parse_article_list(html, section):
    """
    从列表页HTML中解析文章。
    返回 [(title, url, date, section_name), ...]
    """
    soup = BeautifulSoup(html, "lxml")
    articles = []

    # 尝试多种常见列表结构
    # 结构1: <li><h4><a href="...">title</a><span class="time">date</span></h4></li>
    for item in soup.select("li h4"):
        a_tag = item.find("a")
        if not a_tag:
            continue
        href = a_tag.get("href", "")
        title = a_tag.get_text(strip=True)
        if not title or not href:
            continue

        # 提取日期
        date_span = item.find("span", class_="time")
        date_str = date_span.get_text(strip=True) if date_span else ""

        # 补全URL
        if href.startswith("/"):
            full_url = urljoin(BASE_URL, href)
        elif href.startswith("http"):
            full_url = href
        else:
            full_url = urljoin(BASE_URL, "/" + href)

        articles.append((title, full_url, date_str, section["name"]))

    # 结构2: 直接 <a> 标签加 <span class="time">
    if not articles:
        for a_tag in soup.select("a[href]"):
            href = a_tag.get("href", "")
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            parent = a_tag.find_parent("li") or a_tag.find_parent("div")
            date_span = parent.find("span", class_="time") if parent else None
            date_str = date_span.get_text(strip=True) if date_span else ""
            if href.startswith("/"):
                full_url = urljoin(BASE_URL, href)
            elif href.startswith("http"):
                full_url = href
            else:
                continue
            articles.append((title, full_url, date_str, section["name"]))

    return articles


def fetch_section(section):
    """抓取一个栏目的文章列表"""
    print(f"  📥 正在抓取 [{section['name']}] ...")
    html = fetch_page(section["list_url"])
    if not html:
        return []

    articles = parse_article_list(html, section)

    # 进一步过滤：只取近期文章（30天内）
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=30)
    recent = []
    for title, url, date_str, sec_name in articles:
        if date_str:
            try:
                art_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                if art_date < cutoff:
                    continue
            except ValueError:
                pass  # 日期格式无法解析，保留
        recent.append((title, url, date_str, sec_name))

    print(f"    → 解析到 {len(articles)} 条，近期 {len(recent)} 条")
    return recent


# ═══════════════════════════════════════════
#  微信文章搜索模块（搜狗微信）
# ═══════════════════════════════════════════

WECHAT_ACCOUNTS = [
    "苏州人社",
    "苏州人力资源和社会保障局",
    "苏州人才中心",
    "苏州就业",
]


def search_wechat_articles(keyword, timeout=15):
    """
    通过搜狗微信搜索公众号文章。
    返回 [(title, url, date, source_name), ...]
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://weixin.sogou.com/",
    }

    # 搜索公众号文章：type=2 表示搜公众号
    search_url = (
        f"https://weixin.sogou.com/weixin"
        f"?type=2&query={requests.utils.quote(keyword)}"
        f"&ie=utf8"
    )

    try:
        resp = requests.get(search_url, headers=headers, timeout=timeout)
        resp.encoding = "utf-8"

        if resp.status_code != 200:
            print(f"  ⚠️ 搜狗搜索返回 {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        articles = []

        # 搜狗微信搜索结果结构
        for item in soup.select(".news-box .news-list2 li, .wx-rb-wrapper .wx-rb-item"):
            a_tag = item.select_one("a[href]")
            if not a_tag:
                continue
            href = a_tag.get("href", "")
            title = a_tag.get("title") or a_tag.get_text(strip=True)
            if not title or not href:
                continue

            # 提取日期
            date_span = item.select_one(".s-p, .time, span[class*=time]")
            date_str = date_span.get_text(strip=True) if date_span else ""

            # 来源描述
            source_text = f"微信公众号·{keyword}"

            # 补全URL
            if href.startswith("//"):
                full_url = "https:" + href
            elif href.startswith("/"):
                full_url = "https://weixin.sogou.com" + href
            else:
                full_url = href

            articles.append((title, full_url, date_str, source_text))

        # 去重
        seen = set()
        unique = []
        for art in articles:
            key = art[0][:30]
            if key not in seen:
                seen.add(key)
                unique.append(art)

        print(f"    → 搜狗搜索 '{keyword}' 获得 {len(unique)} 条")
        return unique

    except requests.RequestException as e:
        print(f"  ⚠️ 搜狗微信搜索失败: {e}")
        return []


def fetch_wechat_articles():
    """抓取所有已配置公众号的最新文章"""
    print(f"  📱 正在搜索微信公众号文章 ...")
    all_articles = []
    for account in WECHAT_ACCOUNTS:
        arts = search_wechat_articles(account)
        all_articles.extend(arts)
    return all_articles


# ═══════════════════════════════════════════
#  关键词过滤引擎
# ═══════════════════════════════════════════

def is_relevant(title, desc=""):
    """
    判断文章是否与 AI/技能培训/创新创业 相关。
    返回 (is_relevant, matched_keywords, category)
    """
    text = f"{title} {desc}".lower()

    # 排除检查
    for kw in EXCLUDE_KEYWORDS:
        if kw in text:
            return False, [], ""

    matched_ai = [kw for kw in AI_KEYWORDS if kw.lower() in text]
    matched_skills = [kw for kw in SKILLS_KEYWORDS if kw.lower() in text]

    # AI关键词匹配 → "AI技术"
    # 技能关键词匹配 → "技能培训"
    # 都匹配 → "AI+技能"

    if matched_ai and matched_skills:
        return True, matched_ai + matched_skills, "🤖 AI + 技能培训"
    elif matched_ai:
        return True, matched_ai, "🤖 AI 技术前沿"
    elif matched_skills:
        # 如果只匹配技能关键词，需要至少2个或包含强相关词
        strong_skills = ["培训", "技能", "大赛", "竞赛", "创新", "创业", "课程", "讲座"]
        if len(matched_skills) >= 2 or any(k in text for k in strong_skills):
            return True, matched_skills, "📚 技能培训 & 创新创业"
        return False, [], ""

    return False, [], ""


def classify_article(title, url, date_str, source, desc=""):
    """
    完整分类处理一篇文章。
    返回 dict 或 None（不相关时）
    """
    relevant, keywords, category = is_relevant(title, desc)
    if not relevant:
        return None

    return {
        "title": title.strip(),
        "url": url,
        "date": date_str,
        "source": source,
        "category": category,
        "keywords": keywords,
    }


# ═══════════════════════════════════════════
#  获取文章详情（用于提取简介）
# ═══════════════════════════════════════════

def fetch_article_summary(url, timeout=10):
    """抓取文章详情页，提取前150字作为摘要"""
    html = fetch_page(url, timeout=timeout)
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    # 尝试常见正文容器
    for selector in [
        ".article-content", ".content", "#content", ".TRS_Editor",
        ".pages_content", ".bt_content", ".con_text", "article",
        ".maintext", ".text",
    ]:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator=" ", strip=True)
            if len(text) > 20:
                return text[:150] + ("…" if len(text) > 150 else "")
    # 回退：取 body 第一个有较多文字的段落
    for p in soup.select("p"):
        t = p.get_text(strip=True)
        if len(t) > 30:
            return t[:150] + ("…" if len(t) > 150 else "")
    return ""


# ═══════════════════════════════════════════
#  飞书消息推送
# ═══════════════════════════════════════════

def send_feishu_card(date_str, grouped_articles, total_found, total_new):
    """通过 Webhook 发送飞书消息卡片"""
    if not FEISHU_WEBHOOK:
        print("  ⚠️ 未配置 FEISHU_WEBHOOK，跳过飞书推送")
        return False

    # 按分类分组
    categories = {}
    for art in grouped_articles:
        cat = art["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(art)

    # 构建卡片元素
    elements = []

    # 头部概要
    summary_lines = [
        f"**📅 {date_str}**",
        f"📊 今日扫描 **{total_found}** 条，其中新增相关 **{total_new}** 条",
    ]
    elements.append({"tag": "markdown", "content": "\n".join(summary_lines)})
    elements.append({"tag": "hr"})

    # 按类别输出
    cat_order = ["🤖 AI + 技能培训", "🤖 AI 技术前沿", "📚 技能培训 & 创新创业"]
    for cat_name in cat_order:
        if cat_name not in categories:
            continue
        items = categories[cat_name]
        lines = [f"**{cat_name}**（{len(items)}条）"]
        for art in items[:10]:  # 每类最多10条
            t = art["title"].replace("|", "·").replace("\n", " ")
            url = art["url"]
            date_info = f" [{art['date']}]" if art["date"] else ""
            if url:
                lines.append(f"▸ [{t}]({url}){date_info}")
            else:
                lines.append(f"▸ {t}{date_info}")

        elements.append({"tag": "markdown", "content": "\n".join(lines)})
        elements.append({"tag": "hr"})

    # 来源说明脚注
    elements.append({
        "tag": "note",
        "elements": [
            {"tag": "plain_text", "content": "数据来源：苏州市人社局 · 苏州市工信局 · 搜狗微信搜索 | 每日8:30更新"}
        ],
    })

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🏛️ 苏州人社 · 每日信息速递"},
            "template": "blue",
        },
        "elements": elements,
    }

    payload = {"msg_type": "interactive", "card": card}
    headers = {"Content-Type": "application/json"}

    try:
        resp = requests.post(
            FEISHU_WEBHOOK,
            headers=headers,
            json=payload,
            timeout=30,
        )
        result = resp.json()
        if result.get("code") == 0:
            print(f"  ✅ 飞书消息卡片已发送")
            return True
        else:
            print(f"  ⚠️ 飞书发送返回: {result}")
            return False
    except requests.RequestException as e:
        print(f"  ⚠️ 飞书请求异常: {e}")
        return False


# ═══════════════════════════════════════════
#  数据持久化（保存当日报文供调试）
# ═══════════════════════════════════════════

def save_daily_report(date_str, all_articles, relevant_articles):
    """保存当天完整的抓取报告 JSON"""
    report = {
        "date": date_str,
        "total_scanned": len(all_articles),
        "total_relevant": len(relevant_articles),
        "articles": all_articles,
        "relevant_articles": relevant_articles,
    }
    file_path = OUTPUT_DIR / f"report_{datetime.date.today().isoformat()}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  📁 报告已保存: {file_path.name}")
    return file_path


# ═══════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════

def main():
    print("=" * 55)
    print("  苏州人社 · 每日信息速递")
    print("=" * 55)

    today = datetime.date.today()
    weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][today.weekday()]
    date_str = f"{today.year}年{today.month}月{today.day}日 {weekday_cn}"

    # ── 1. 抓取网站栏目 ──
    print("\n🏛️ 抓取官网栏目 ...")
    all_articles = []
    for section in SECTIONS:
        arts = fetch_section(section)
        all_articles.extend(arts)

    # ── 2. 抓取微信文章 ──
    print("\n📱 搜索微信文章 ...")
    wechat_arts = fetch_wechat_articles()
    # 微信文章格式兼容
    for art in wechat_arts:
        all_articles.append(art)

    print(f"\n📊 共获取 {len(all_articles)} 条原始内容")

    # ── 3. 关键词过滤 ──
    print("\n🔍 AI/技能关键词过滤 ...")
    cache = load_cache()
    relevant = []
    new_relevant = []
    total_checked = 0

    # 先去重（相同标题+URL视为重复）
    seen_raw = set()
    unique_articles = []
    for art in all_articles:
        title, url, date_str_item, source = art[0], art[1], art[2], art[3]
        key = f"{url}|{title[:30]}"
        if key not in seen_raw:
            seen_raw.add(key)
            unique_articles.append(art)

    for art in unique_articles:
        title, url, date_str_item, source = art[0], art[1], art[2], art[3]
        total_checked += 1

        result = classify_article(title, url, date_str_item, source)
        if result is None:
            continue

        # 尝试获取摘要（仅对新的相关文章）
        cache_key = make_key(url, title)
        if cache_key not in cache:
            summary = fetch_article_summary(url)
            result["summary"] = summary
            new_relevant.append(result)
            cache.add(cache_key)
        else:
            result["summary"] = ""
            # 仍加入相关列表但标记为已推送
            result["summary"] = "（已推送过）"

        relevant.append(result)

    # 保存缓存
    save_cache(cache)

    # 分类统计
    cat_counts = {}
    for r in relevant:
        c = r["category"]
        cat_counts[c] = cat_counts.get(c, 0) + 1

    print(f"  共检查 {total_checked} 条，相关 {len(relevant)} 条，新增 {len(new_relevant)} 条")
    for cat, cnt in cat_counts.items():
        print(f"    {cat}: {cnt}条")
    for r in new_relevant:
        kw_display = ", ".join(r["keywords"][:5])
        print(f"    ✓ {r['title'][:50]} [{kw_display}]")

    # ── 4. 保存当日报告 ──
    save_daily_report(date_str, unique_articles, relevant)

    # ── 5. 推送飞书 ──
    if new_relevant:
        print("\n📤 推送到飞书 ...")
        send_feishu_card(date_str, new_relevant, total_checked, len(new_relevant))
    else:
        print("\n📤 无新增相关内容，跳过飞书推送")
        # 仍然发送一条简单的"今日无更新"消息
        if FEISHU_WEBHOOK:
            no_update_card(date_str)

    print("\n" + "=" * 55)
    print("  ✅ 全部完成！")
    print(f"  📁 报告: {OUTPUT_DIR}")
    print("=" * 55)


def no_update_card(date_str):
    """发送无更新通知"""
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🏛️ 苏州人社 · 每日信息速递"},
            "template": "blue",
        },
        "elements": [
            {"tag": "markdown", "content": f"**📅 {date_str}**\n\n今日暂未检测到新的AI/技能培训相关内容。"},
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": "数据来源：苏州市人社局 · 苏州市工信局 · 搜狗微信搜索 | 每日8:30更新"}
                ],
            },
        ],
    }
    payload = {"msg_type": "interactive", "card": card}
    try:
        resp = requests.post(
            FEISHU_WEBHOOK,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        if resp.json().get("code") == 0:
            print(f"  ✅ 已发送无更新通知")
    except Exception as e:
        print(f"  ⚠️ 发送无更新通知失败: {e}")


if __name__ == "__main__":
    main()

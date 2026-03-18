"""
FleetBot — TechTrend NB Source Bot + Trend Scanner
Discord slash commands for tracking NotebookLM source additions
and daily GitHub trending analysis.

Commands:
  /nb-add         — Record a new URL to add to NotebookLM
  /nb-list        — List pending sources (this week or all)
  /nb-done        — Mark a source as added to NB
  /nb-weekly-sync — Export this week's additions as markdown
  /nb-stats       — Show source counts per notebook
  /trend-scan     — Scan today's GitHub trending repos for project relevance
"""

import codecs
import os
import re
import json
import discord
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timedelta, timezone, time as dt_time
from notion_client import Client as NotionClient
import httpx

# Only load .env file if it exists (local dev). Railway uses system env vars.
from pathlib import Path
if Path(".env").exists():
    from dotenv import load_dotenv
    load_dotenv(override=False)

# ── Config ──────────────────────────────────────────────────
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DB_ID")
GUILD_ID = os.getenv("GUILD_ID")
TECHTREND_CHANNEL_ID = os.getenv("TECHTREND_CHANNEL_ID")

print(f"ENV check: DISCORD_TOKEN={'✅' if DISCORD_TOKEN else '❌'} "
      f"NOTION_TOKEN={'✅' if NOTION_TOKEN else '❌'} "
      f"NOTION_DB_ID={'✅' if NOTION_DB_ID else '❌'} "
      f"GUILD_ID={'✅' if GUILD_ID else '❌'} "
      f"TECHTREND_CHANNEL_ID={'✅' if TECHTREND_CHANNEL_ID else '❌'}")

assert DISCORD_TOKEN, "Missing DISCORD_TOKEN — set in Railway Variables or .env"
assert NOTION_TOKEN, "Missing NOTION_TOKEN — set in Railway Variables or .env"
assert NOTION_DB_ID, "Missing NOTION_DB_ID — set in Railway Variables or .env"

# ── Clients ─────────────────────────────────────────────────
intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
notion = NotionClient(auth=NOTION_TOKEN)

# ── Timezone ────────────────────────────────────────────────
TW = timezone(timedelta(hours=8))

# ── NB choices ──────────────────────────────────────────────
NB_CHOICES = [
    app_commands.Choice(name="NB1 — AI 模型 & 工具", value="NB1"),
    app_commands.Choice(name="NB2 — 開發框架 & 語言", value="NB2"),
    app_commands.Choice(name="NB3 — DevOps & Infra", value="NB3"),
    app_commands.Choice(name="NB4 — 商業化 & 產品", value="NB4"),
]

NB_LABELS = {
    "NB1": "📘 NB1 AI 模型 & 工具",
    "NB2": "📗 NB2 開發框架 & 語言",
    "NB3": "📙 NB3 DevOps & Infra",
    "NB4": "📕 NB4 商業化 & 產品",
}

NB_EMOJI = {"NB1": "📘", "NB2": "📗", "NB3": "📙", "NB4": "📕"}


# ── Helpers ──────────────────────────────────────────────────
def validate_url(url: str) -> bool:
    pattern = re.compile(
        r"^https?://"
        r"(?:[a-zA-Z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+)$"
    )
    return bool(pattern.match(url))


def now_tw() -> datetime:
    return datetime.now(TW)


def week_start() -> datetime:
    today = now_tw().replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=today.weekday())


def format_date_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


# ── Notion Operations ───────────────────────────────────────
def notion_add_source(nb: str, url: str, note: str, project: str | None = None) -> dict:
    properties = {
        "URL": {"url": url},
        "Notebook": {"select": {"name": nb}},
        "Note": {"rich_text": [{"text": {"content": note}}]},
        "Status": {"select": {"name": "pending"}},
        "Added Date": {"date": {"start": format_date_iso(now_tw())}},
    }
    if project:
        properties["Project"] = {"rich_text": [{"text": {"content": project}}]}

    return notion.pages.create(
        parent={"database_id": NOTION_DB_ID},
        properties=properties,
    )


def notion_query_sources(status: str = "pending", since: datetime | None = None) -> list:
    filters = [{"property": "Status", "select": {"equals": status}}]

    if since:
        filters.append({
            "property": "Added Date",
            "date": {"on_or_after": format_date_iso(since)},
        })

    response = notion.databases.query(
        database_id=NOTION_DB_ID,
        filter={"and": filters} if len(filters) > 1 else filters[0],
        sorts=[{"property": "Added Date", "direction": "descending"}],
    )
    return response.get("results", [])


def notion_update_status(page_id: str, status: str) -> dict:
    return notion.pages.update(
        page_id=page_id,
        properties={
            "Status": {"select": {"name": status}},
            "Synced Date": {"date": {"start": format_date_iso(now_tw())}},
        },
    )


def extract_source_info(page: dict) -> dict:
    props = page["properties"]
    return {
        "id": page["id"],
        "short_id": page["id"][:8],
        "url": props.get("URL", {}).get("url", "N/A"),
        "nb": props.get("Notebook", {}).get("select", {}).get("name", "?"),
        "note": _get_rich_text(props.get("Note", {})),
        "status": props.get("Status", {}).get("select", {}).get("name", "?"),
        "date": props.get("Added Date", {}).get("date", {}).get("start", "?"),
        "project": _get_rich_text(props.get("Project", {})),
    }


def _get_rich_text(prop: dict) -> str:
    texts = prop.get("rich_text", [])
    return texts[0]["text"]["content"] if texts else ""


# ── NB Slash Commands ────────────────────────────────────────

@tree.command(name="nb-add", description="記錄一個待新增到 NotebookLM 的來源 URL")
@app_commands.describe(
    nb="目標 Notebook",
    url="來源 URL",
    note="備註說明（這是什麼、為什麼要加）",
    project="關聯專案（選填）",
)
@app_commands.choices(nb=NB_CHOICES)
@app_commands.choices(project=[
    app_commands.Choice(name="CardSense", value="CardSense"),
    app_commands.Choice(name="RTA", value="RTA"),
    app_commands.Choice(name="SEEDCRAFT", value="SEEDCRAFT"),
    app_commands.Choice(name="TechTrend", value="TechTrend"),
    app_commands.Choice(name="SmartChoice", value="SmartChoice"),
    app_commands.Choice(name="FridgeManager", value="FridgeManager"),
    app_commands.Choice(name="通用（不限專案）", value=""),
])
async def nb_add(
    interaction: discord.Interaction,
    nb: app_commands.Choice[str],
    url: str,
    note: str,
    project: app_commands.Choice[str] | None = None,
):
    if not validate_url(url):
        await interaction.response.send_message(
            f"❌ URL 格式無效：`{url}`\n請確認包含 `https://` 開頭", ephemeral=True
        )
        return

    await interaction.response.defer()

    try:
        proj_value = project.value if project and project.value else None
        page = notion_add_source(nb.value, url, note, proj_value)
        short_id = page["id"][:8]

        embed = discord.Embed(
            title="✅ 來源已記錄",
            color=0x2ECC71,
            timestamp=now_tw(),
        )
        embed.add_field(name="Notebook", value=NB_LABELS[nb.value], inline=True)
        embed.add_field(name="ID", value=f"`{short_id}`", inline=True)
        embed.add_field(name="URL", value=url, inline=False)
        embed.add_field(name="備註", value=note, inline=False)
        if proj_value:
            embed.add_field(name="關聯專案", value=proj_value, inline=True)
        embed.set_footer(text="每周一 /nb-weekly-sync 匯出 → 批次加入 NB")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ Notion 寫入失敗：```{e}```")


@tree.command(name="nb-list", description="列出待新增的來源")
@app_commands.describe(scope="顯示範圍")
@app_commands.choices(scope=[
    app_commands.Choice(name="本周 pending", value="week"),
    app_commands.Choice(name="全部 pending", value="all"),
    app_commands.Choice(name="已完成（本周）", value="done"),
])
async def nb_list(
    interaction: discord.Interaction,
    scope: app_commands.Choice[str] | None = None,
):
    await interaction.response.defer()

    scope_val = scope.value if scope else "week"

    if scope_val == "week":
        sources = notion_query_sources("pending", since=week_start())
        title = f"📋 本周待新增來源（{format_date_iso(week_start())} ~）"
    elif scope_val == "all":
        sources = notion_query_sources("pending")
        title = "📋 全部待新增來源"
    else:
        sources = notion_query_sources("done", since=week_start())
        title = f"✅ 本周已完成（{format_date_iso(week_start())} ~）"

    if not sources:
        await interaction.followup.send(f"{title}\n\n（空）沒有記錄。")
        return

    lines = []
    for page in sources:
        info = extract_source_info(page)
        emoji = NB_EMOJI.get(info["nb"], "📄")
        proj_tag = f" `[{info['project']}]`" if info["project"] else ""
        lines.append(
            f"{emoji} `{info['short_id']}` {info['nb']} — {info['note']}{proj_tag}\n"
            f"   {info['url']}"
        )

    msg = f"**{title}**\n\n" + "\n\n".join(lines) + f"\n\n共 {len(sources)} 筆"
    if len(msg) > 1900:
        msg = msg[:1900] + "\n\n⚠️ 清單過長，請用 `/nb-weekly-sync` 匯出完整版"

    await interaction.followup.send(msg)


@tree.command(name="nb-done", description="標記來源已加入 NotebookLM")
@app_commands.describe(source_id="來源 ID（前 8 碼，從 /nb-list 取得）")
async def nb_done(interaction: discord.Interaction, source_id: str):
    await interaction.response.defer()

    sources = notion_query_sources("pending")
    target = None
    for page in sources:
        if page["id"].startswith(source_id):
            target = page
            break

    if not target:
        await interaction.followup.send(
            f"❌ 找不到 ID `{source_id}` 的 pending 來源。\n用 `/nb-list` 確認 ID。"
        )
        return

    try:
        notion_update_status(target["id"], "done")
        info = extract_source_info(target)
        await interaction.followup.send(
            f"✅ 已標記完成：{NB_EMOJI.get(info['nb'], '📄')} `{info['short_id']}` — {info['note']}\n"
            f"   {info['url']}"
        )
    except Exception as e:
        await interaction.followup.send(f"❌ 更新失敗：```{e}```")


@tree.command(name="nb-weekly-sync", description="匯出本周來源清單為 Markdown（用於更新 URL txt 文件）")
async def nb_weekly_sync(interaction: discord.Interaction):
    await interaction.response.defer()

    sources = notion_query_sources("pending", since=week_start())

    if not sources:
        await interaction.followup.send("本周沒有待新增的來源。")
        return

    grouped: dict[str, list] = {"NB1": [], "NB2": [], "NB3": [], "NB4": []}
    for page in sources:
        info = extract_source_info(page)
        grouped.setdefault(info["nb"], []).append(info)

    lines = [
        f"# NotebookLM 來源更新 — Week of {format_date_iso(week_start())}",
        f"Generated: {now_tw().strftime('%Y-%m-%d %H:%M')} UTC+8",
        "",
    ]

    url_blocks: dict[str, list[str]] = {}

    for nb in ["NB1", "NB2", "NB3", "NB4"]:
        items = grouped.get(nb, [])
        if not items:
            continue
        lines.append(f"## {NB_LABELS[nb]} ({len(items)} 筆)")
        lines.append("")

        url_blocks[nb] = []
        for item in items:
            proj_tag = f" [{item['project']}]" if item["project"] else ""
            lines.append(f"- [ ] {item['note']}{proj_tag}")
            lines.append(f"  {item['url']}")
            url_blocks[nb].append(item["url"])
        lines.append("")

    lines.append("---")
    lines.append("## 純 URL（直接貼入對應 txt 文件）")
    lines.append("")
    for nb in ["NB1", "NB2", "NB3", "NB4"]:
        urls = url_blocks.get(nb, [])
        if not urls:
            continue
        lines.append(f"### {nb}")
        lines.append("```")
        for u in urls:
            lines.append(u)
        lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append("## 同步 Checklist")
    lines.append("- [ ] 加入 NotebookLM 對應 notebook")
    lines.append("- [ ] 更新對應 URL txt 文件")
    lines.append("- [ ] git commit + push to fleet-command")
    lines.append("- [ ] /nb-done 標記所有項目完成")

    md_content = "\n".join(lines)

    if len(md_content) > 1800:
        filename = f"nb-sync-{format_date_iso(now_tw())}.md"
        file = discord.File(
            fp=__import__("io").BytesIO(md_content.encode("utf-8")),
            filename=filename,
        )
        await interaction.followup.send(
            f"📤 本周來源同步清單（{len(sources)} 筆）：", file=file
        )
    else:
        await interaction.followup.send(f"```md\n{md_content}\n```")


@tree.command(name="nb-stats", description="來源統計")
async def nb_stats(interaction: discord.Interaction):
    await interaction.response.defer()

    pending = notion_query_sources("pending")
    done_this_week = notion_query_sources("done", since=week_start())

    pending_by_nb: dict[str, int] = {}
    for page in pending:
        nb = page["properties"].get("Notebook", {}).get("select", {}).get("name", "?")
        pending_by_nb[nb] = pending_by_nb.get(nb, 0) + 1

    done_by_nb: dict[str, int] = {}
    for page in done_this_week:
        nb = page["properties"].get("Notebook", {}).get("select", {}).get("name", "?")
        done_by_nb[nb] = done_by_nb.get(nb, 0) + 1

    embed = discord.Embed(
        title="📊 NB 來源追蹤統計",
        color=0x3498DB,
        timestamp=now_tw(),
    )

    for nb in ["NB1", "NB2", "NB3", "NB4"]:
        p = pending_by_nb.get(nb, 0)
        d = done_by_nb.get(nb, 0)
        bar_p = "🟡" * p if p else ""
        bar_d = "🟢" * d if d else ""
        embed.add_field(
            name=NB_LABELS[nb],
            value=f"Pending: {p} {bar_p}\nDone (本周): {d} {bar_d}",
            inline=False,
        )

    embed.set_footer(text=f"Total pending: {len(pending)} | Done this week: {len(done_this_week)}")
    await interaction.followup.send(embed=embed)


# ── Trend Scan: Config ──────────────────────────────────────

PROJECT_KEYWORDS: dict[str, list[str]] = {
    "CardSense": [
        "credit card", "payment", "fintech", "bank api", "stripe",
        "financial", "rewards", "cashback", "promo", "billing",
    ],
    "RTA": [
        "review", "trust", "credibility", "fine-tuning", "fine-tune",
        "embedding", "google maps", "sentiment", "fake review",
        "annotation", "knowledge distillation", "sft", "rlhf", "dpo",
    ],
    "SEEDCRAFT": [
        "line bot", "line sdk", "education", "parenting", "chatbot",
        "coaching", "children", "family", "edtech",
    ],
    "TechTrend": [
        "rss", "newsletter", "content pipeline", "briefing",
        "curation", "news aggregat", "tech digest",
    ],
    "Knoty": [
        "social graph", "relationship", "notification listener",
        "contact", "social network analysis",
    ],
    "Agent/Infra": [
        "mcp", "agent", "orchestration", "skills", "claude code",
        "agentic", "multi-agent", "tool use", "function calling",
        "security hardening", "prompt injection",
    ],
}

TECH_KEYWORDS: list[str] = [
    "typescript", "fastapi", "supabase", "railway", "vercel",
    "ollama", "qwen", "react native", "discord bot", "discord.js",
    "cloudflare workers", "n8n", "notion api", "spring boot",
    "postgresql", "docker", "next.js", "nextjs", "tailwind",
    "shadcn", "unsloth", "lora", "qlora", "vllm",
]

EXCLUDE_PATTERNS: list[str] = [
    r"awesome-",
    r"free-programming-books",
    r"coding-interview",
    r"build-your-own",
    r"system-design-primer",
    r"project-based-learning",
    r"public-apis/public-apis",
    r"TheAlgorithms/",
    r"freeCodeCamp/freeCodeCamp",
]


# ── Trend Scan: Fetch ───────────────────────────────────────
async def fetch_trendshift() -> list[dict]:
    """Fetch trendshift.io and extract repo data from RSC initialData payload."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        resp = await client.get(
            "https://trendshift.io/",
            headers={"User-Agent": "FleetBot/1.0 (TechTrend scan)"},
        )
        resp.raise_for_status()
        html = resp.text

    match = re.search(
        r'\\"initialData\\":\s*(\[.*?\])\s*\}',
        html,
        re.DOTALL,
    )

    if not match:
        print("[trend-scan] Could not find initialData in page")
        return []

    try:
        raw = match.group(1)
        raw = codecs.decode(raw, 'unicode_escape')
        repos_raw = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"[trend-scan] Parse failed: {e}")
        return []

    repos = []
    for r in repos_raw:
        stars = r.get("repository_stars", 0)
        forks = r.get("repository_forks", 0)
        name = r.get("full_name", "")
        repos.append({
            "rank": r.get("rank", 0),
            "name": name,
            "language": r.get("repository_language", ""),
            "stars": _format_count(stars),
            "stars_raw": stars,
            "forks": _format_count(forks),
            "description": r.get("repository_description", "") or "",
            "score": r.get("score", 0),
            "github_url": f"https://github.com/{name}",
            "trendshift_url": f"https://trendshift.io/repositories/{r.get('repository_id', '')}",
        })

    print(f"[trend-scan] Parsed {len(repos)} repos")
    return repos


def _format_count(n: int | float | str) -> str:
    if isinstance(n, str):
        return n
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


# ── Trend Scan: Match ───────────────────────────────────────
def _should_exclude(repo: dict) -> bool:
    text = f"{repo['name']} {repo['description']}"
    return any(re.search(p, text, re.IGNORECASE) for p in EXCLUDE_PATTERNS)


def _match_repo(repo: dict) -> dict | None:
    search_text = f"{repo['name']} {repo['description']} {repo['language']}".lower()

    matched_projects: list[str] = []
    for project, keywords in PROJECT_KEYWORDS.items():
        if any(kw in search_text for kw in keywords):
            matched_projects.append(project)

    matched_tech = [kw for kw in TECH_KEYWORDS if kw in search_text]

    if not matched_projects and not matched_tech:
        return None

    return {
        "repo": repo,
        "matched_projects": matched_projects,
        "matched_tech": matched_tech,
        "priority": "high" if matched_projects else "medium",
    }


# ── Trend Scan: Format ──────────────────────────────────────
def _build_trend_embed(match: dict) -> discord.Embed:
    repo = match["repo"]
    emoji = "🔴" if match["priority"] == "high" else "🟡"
    color = 0xFF4444 if match["priority"] == "high" else 0xFFAA00

    tags = " ".join(
        [f"`{p}`" for p in match["matched_projects"]]
        + [f"`{t}`" for t in match["matched_tech"]]
    )

    embed = discord.Embed(
        title=f"{emoji} {repo['name']}",
        url=repo["github_url"],
        description=repo["description"][:200] if repo["description"] else "_(no description)_",
        color=color,
    )
    embed.add_field(name="Stars", value=repo["stars"], inline=True)
    if repo["language"]:
        embed.add_field(name="Language", value=repo["language"], inline=True)
    embed.add_field(name="Rank", value=f"#{repo['rank']}", inline=True)
    embed.add_field(name="匹配", value=tags, inline=False)
    embed.set_footer(text=f"Trendshift Daily | {format_date_iso(now_tw())}")
    return embed


async def _run_trend_scan(keyword_filter: str | None = None) -> list[dict]:
    try:
        repos = await fetch_trendshift()
        if not repos:
            return []

        results = []
        for repo in repos:
            if _should_exclude(repo):
                continue
            m = _match_repo(repo)
            if m is None:
                continue
            if keyword_filter:
                kw = keyword_filter.lower()
                all_text = (
                    f"{repo['name']} {repo['description']} "
                    f"{' '.join(m['matched_projects'])} {' '.join(m['matched_tech'])}"
                ).lower()
                if kw not in all_text:
                    continue
            results.append(m)

        results.sort(key=lambda m: (0 if m["priority"] == "high" else 1, m["repo"]["rank"]))
        return results

    except Exception as e:
        print(f"[trend-scan] Error: {e}")
        return []


# ── Trend Scan: Slash Command ───────────────────────────────
@tree.command(name="trend-scan", description="掃描今日 GitHub trending，推送與專案相關的 repo")
@app_commands.describe(
    keyword="額外過濾關鍵字 (e.g. 'agent', 'fine-tuning')",
    show_all="顯示所有 trending repo（不過濾）",
)
async def trend_scan(
    interaction: discord.Interaction,
    keyword: str | None = None,
    show_all: bool = False,
):
    await interaction.response.defer()

    if show_all:
        try:
            repos = await fetch_trendshift()
            if not repos:
                await interaction.followup.send("❌ 無法取得 Trendshift 資料")
                return
            lines = []
            for repo in repos[:25]:
                lines.append(
                    f"**#{repo['rank']}** [{repo['name']}]({repo['github_url']}) "
                    f"⭐{repo['stars']} | {repo['language'] or '?'}"
                )
            msg = f"📋 **Trendshift 今日 Top {len(repos)}**\n\n" + "\n".join(lines)
            if len(msg) > 1900:
                msg = msg[:1900] + "\n..."
            await interaction.followup.send(msg)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"❌ 取得失敗：```{type(e).__name__}: {e}```")
        return

    results = await _run_trend_scan(keyword_filter=keyword)

    if not results:
        filter_note = f"（關鍵字: `{keyword}`）" if keyword else ""
        await interaction.followup.send(
            f"📡 今日掃描完成 — 無相關 repo{filter_note}\n"
            f"_(使用 `/trend-scan show_all:True` 查看完整清單)_"
        )
        return

    high = [r for r in results if r["priority"] == "high"]
    medium = [r for r in results if r["priority"] == "medium"]

    filter_note = f" | 關鍵字: `{keyword}`" if keyword else ""
    await interaction.followup.send(
        f"📡 **今日趨勢掃描完成** — "
        f"{len(high)} 個🔴高相關 + {len(medium)} 個🟡技術棧相關{filter_note}"
    )

    for m in results[:10]:
        embed = _build_trend_embed(m)
        await interaction.channel.send(embed=embed)


# ── Trend Scan: Daily Cron ──────────────────────────────────
@tasks.loop(time=dt_time(hour=0, minute=0))  # 00:00 UTC = 08:00 UTC+8
async def daily_trend_scan():
    if not TECHTREND_CHANNEL_ID:
        return

    channel = bot.get_channel(int(TECHTREND_CHANNEL_ID))
    if not channel:
        print(f"[trend-scan] Channel {TECHTREND_CHANNEL_ID} not found")
        return

    results = await _run_trend_scan()
    if not results:
        return

    high = [r for r in results if r["priority"] == "high"]
    medium = [r for r in results if r["priority"] == "medium"]

    await channel.send(
        f"📡 **每日趨勢掃描** ({format_date_iso(now_tw())}) — "
        f"{len(high)} 個🔴高相關 + {len(medium)} 個🟡技術棧相關"
    )

    for m in results[:10]:
        embed = _build_trend_embed(m)
        await channel.send(embed=embed)


@daily_trend_scan.before_loop
async def before_daily_scan():
    await bot.wait_until_ready()


# ── Bot Events ───────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"🤖 {bot.user} is online!")

    if GUILD_ID:
        guild = discord.Object(id=int(GUILD_ID))
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
        print(f"✅ Slash commands synced to guild {GUILD_ID}")
    else:
        await tree.sync()
        print("✅ Slash commands synced globally (may take up to 1 hour)")

    if TECHTREND_CHANNEL_ID:
        daily_trend_scan.start()
        print(f"✅ Daily trend scan → channel {TECHTREND_CHANNEL_ID}")

    print("Commands: /nb-add, /nb-list, /nb-done, /nb-weekly-sync, /nb-stats, /trend-scan")


# ── Entry Point ──────────────────────────────────────────────
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
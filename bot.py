"""
TechTrend NB Source Bot — Phase 0
Discord slash commands for tracking NotebookLM source additions.
Writes to Notion DB, syncs with fleet-command repo on weekly basis.

Commands:
  /nb-add     — Record a new URL to add to NotebookLM
  /nb-list    — List pending sources (this week or all)
  /nb-done    — Mark a source as added to NB
  /nb-weekly-sync — Export this week's additions as markdown
  /nb-stats   — Show source counts per notebook
"""

import os
import re
import discord
from discord import app_commands
from datetime import datetime, timedelta, timezone
from notion_client import Client as NotionClient
from dotenv import load_dotenv

load_dotenv()

# ── Config ──────────────────────────────────────────────────
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DB_ID")
GUILD_ID = os.getenv("GUILD_ID")  # Your Discord server ID (for instant slash command sync)

assert DISCORD_TOKEN, "Missing DISCORD_TOKEN in .env"
assert NOTION_TOKEN, "Missing NOTION_TOKEN in .env"
assert NOTION_DB_ID, "Missing NOTION_DB_ID in .env"

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

# NB display mapping
NB_LABELS = {
    "NB1": "📘 NB1 AI 模型 & 工具",
    "NB2": "📗 NB2 開發框架 & 語言",
    "NB3": "📙 NB3 DevOps & Infra",
    "NB4": "📕 NB4 商業化 & 產品",
}

NB_EMOJI = {"NB1": "📘", "NB2": "📗", "NB3": "📙", "NB4": "📕"}


# ── Helpers ──────────────────────────────────────────────────
def validate_url(url: str) -> bool:
    """Basic URL validation."""
    pattern = re.compile(
        r"^https?://"
        r"(?:[a-zA-Z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+)$"
    )
    return bool(pattern.match(url))


def now_tw() -> datetime:
    return datetime.now(TW)


def week_start() -> datetime:
    """Monday 00:00 of current week (UTC+8)."""
    today = now_tw().replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=today.weekday())


def format_date_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


# ── Notion Operations ───────────────────────────────────────
def notion_add_source(nb: str, url: str, note: str, project: str | None = None) -> dict:
    """Create a new page in the Notion source tracking DB."""
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
    """Query sources from Notion DB with optional date filter."""
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
    """Update a source's status."""
    return notion.pages.update(
        page_id=page_id,
        properties={
            "Status": {"select": {"name": status}},
            "Synced Date": {"date": {"start": format_date_iso(now_tw())}},
        },
    )


def extract_source_info(page: dict) -> dict:
    """Extract readable info from a Notion page."""
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


# ── Slash Commands ───────────────────────────────────────────

# /nb-add
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


# /nb-list
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
    # Discord message limit = 2000 chars
    if len(msg) > 1900:
        msg = msg[:1900] + "\n\n⚠️ 清單過長，請用 `/nb-weekly-sync` 匯出完整版"

    await interaction.followup.send(msg)


# /nb-done
@tree.command(name="nb-done", description="標記來源已加入 NotebookLM")
@app_commands.describe(source_id="來源 ID（前 8 碼，從 /nb-list 取得）")
async def nb_done(interaction: discord.Interaction, source_id: str):
    await interaction.response.defer()

    # Find the page by short ID prefix
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


# /nb-weekly-sync
@tree.command(name="nb-weekly-sync", description="匯出本周來源清單為 Markdown（用於更新 URL txt 文件）")
async def nb_weekly_sync(interaction: discord.Interaction):
    await interaction.response.defer()

    sources = notion_query_sources("pending", since=week_start())

    if not sources:
        await interaction.followup.send("本周沒有待新增的來源。")
        return

    # Group by NB
    grouped: dict[str, list] = {"NB1": [], "NB2": [], "NB3": [], "NB4": []}
    for page in sources:
        info = extract_source_info(page)
        grouped.setdefault(info["nb"], []).append(info)

    # Build markdown
    lines = [
        f"# NotebookLM 來源更新 — Week of {format_date_iso(week_start())}",
        f"Generated: {now_tw().strftime('%Y-%m-%d %H:%M')} UTC+8",
        "",
    ]

    url_blocks: dict[str, list[str]] = {}  # For URL-only appendix

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

    # URL-only section for easy copy-paste into txt files
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

    # Checklist
    lines.append("---")
    lines.append("## 同步 Checklist")
    lines.append("- [ ] 加入 NotebookLM 對應 notebook")
    lines.append("- [ ] 更新對應 URL txt 文件")
    lines.append("- [ ] git commit + push to fleet-command")
    lines.append("- [ ] /nb-done 標記所有項目完成")

    md_content = "\n".join(lines)

    # Send as file attachment if too long, otherwise inline
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


# /nb-stats
@tree.command(name="nb-stats", description="來源統計")
async def nb_stats(interaction: discord.Interaction):
    await interaction.response.defer()

    pending = notion_query_sources("pending")
    done_this_week = notion_query_sources("done", since=week_start())

    # Count by NB
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

    print("Commands: /nb-add, /nb-list, /nb-done, /nb-weekly-sync, /nb-stats")


# ── Entry Point ──────────────────────────────────────────────
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)

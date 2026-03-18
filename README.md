# FleetBot — Discord 智慧助手

> NotebookLM 來源追蹤 + GitHub Trending 每日掃描

## 架構

```
Discord Slash Commands
        │
        ▼
  Python Bot (discord.py)
        │
        ├──▶ Notion DB「NB 來源追蹤」
        │       （/nb-add, /nb-list, /nb-done, /nb-weekly-sync, /nb-stats）
        │
        └──▶ Trendshift.io (GitHub Trending)
                （/trend-scan, 每日自動掃描 08:00 台灣時間）
```

---

## 技術棧

| 項目 | 技術 |
|------|------|
| 語言 | Python 3.12+ |
| Bot 框架 | discord.py ≥2.3.0 |
| HTTP Client | httpx ≥0.28.1 |
| Notion SDK | notion-client ≥2.2.0 |
| 套件管理 | uv（使用 pyproject.toml） |
| 部署 | Railway.app（Nixpacks） |
| Linter | ruff ≥0.4.0 |

---

## 1. 環境變數

```
DISCORD_TOKEN          # Discord Bot Token
GUILD_ID               # Discord Server ID
NOTION_TOKEN           # Notion Integration Token
NOTION_DB_ID           # Notion Database ID（32 字元）
TECHTREND_CHANNEL_ID   # 每日趨勢報告頻道 ID（選填）
```

---

## 2. Notion DB 設定

在 Notion workspace 建立 Database，屬性如下：

| 屬性名稱 | 類型 | 選項 |
|---------|------|------|
| **Title** | Title | （Notion 預設） |
| **URL** | URL | — |
| **Notebook** | Select | `NB1`, `NB2`, `NB3`, `NB4` |
| **Note** | Rich Text | — |
| **Status** | Select | `pending`, `done`, `skipped` |
| **Added Date** | Date | — |
| **Synced Date** | Date | — |
| **Project** | Rich Text | — |

### Notebook 分類

| Notebook | 領域 |
|----------|------|
| NB1 | AI 模型 & 工具 |
| NB2 | 開發框架 & 語言 |
| NB3 | DevOps & Infra |
| NB4 | 商業化 & 產品 |

### 取得 Database ID

1. 瀏覽器開啟 DB 頁面
2. URL 格式：`https://notion.so/{workspace}/{database_id}?v=...`
3. 複製 `database_id`（32 字元，無 dash）
4. 確認 Integration 已 **Connect** 到該 DB

---

## 3. Discord Bot 設定

### Discord Developer Portal

1. https://discord.com/developers/applications → 建立新 Application
2. **Bot** → 取得 Token
3. **OAuth2** → URL Generator：
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Attach Files`
4. 用生成的 URL 邀請 bot 到 server

### 取得 Guild ID

1. Discord 設定 → 進階 → 開啟「開發者模式」
2. 右鍵 server → 複製伺服器 ID

---

## 4. 指令一覽

### NB 來源追蹤

#### `/nb-add` — 記錄新來源

```
/nb-add nb:NB1 url:https://qwen.readthedocs.io/en/latest/ note:Qwen3 官方文件 project:RTA
```

- `nb`：必填，選擇 NB1-NB4
- `url`：必填，http:// 或 https:// 開頭
- `note`：必填，簡述內容
- `project`：選填，關聯專案

#### `/nb-list` — 查看清單

```
/nb-list scope:本周 pending     ← 預設
/nb-list scope:全部 pending
/nb-list scope:已完成（本周）
```

#### `/nb-done` — 標記完成

```
/nb-done source_id:a1b2c3d4
```

ID 從 `/nb-list` 取得（前 8 碼）。

#### `/nb-weekly-sync` — 匯出同步清單

輸出包含：
- 按 NB 分組的來源清單（含 checkbox）
- 純 URL 區塊（直接貼入 txt 文件）
- 同步 checklist
- 內容過長時自動輸出為檔案

#### `/nb-stats` — 統計面板

顯示各 NB 的 pending / done 數量與視覺化進度條。

### GitHub Trending 掃描

#### `/trend-scan` — 手動掃描

```
/trend-scan                    ← 掃描全部，自動篩選相關 repo
/trend-scan keyword:fastapi    ← 依關鍵字篩選
/trend-scan show_all:True      ← 顯示所有趨勢 repo（不篩選）
```

自動依 6 個專案關鍵字匹配（CardSense、RTA、SEEDCRAFT、TechTrend、Knoty、Agent/Infra），並以優先級分類：
- **High**：與專案直接相關
- **Medium**：與技術棧相關（TypeScript、FastAPI、Supabase、Railway 等）

自動排除 meta-learning repo（awesome-\*、algorithms、interview prep）。

#### 每日自動掃描

- 每日 00:00 UTC（08:00 台灣時間）自動執行
- 結果發送至 `TECHTREND_CHANNEL_ID` 指定的頻道
- 需設定 `TECHTREND_CHANNEL_ID` 環境變數

---

## 5. 每周同步流程

```
每周一（30 分鐘內）：

1. /nb-weekly-sync
   → 取得本周所有 pending 來源的 markdown

2. 按 NB 分組，將 URL 加入：
   a. NotebookLM 對應 notebook
   b. fleet-command repo 的對應 txt 文件
      - AI-Links-URLs-Only.txt (NB1)
      - NB2-Dev-Frameworks-URLs.txt (NB2)
      - NB3-DevOps-Infra-URLs.txt (NB3)
      - NB4-Commercial-Product-URLs.txt (NB4)

3. git commit + push

4. /nb-done {id} 逐一標記完成
   （或在 Notion 批次改 status）

5. 繼續跑 TechTrend 周報 prompt
```

---

## 6. 部署

### Railway 部署

1. https://railway.app → New Project → Deploy from GitHub Repo
2. 選擇 `fleetbot` repo
3. Nixpacks 自動偵測 `pyproject.toml` + 安裝 uv
4. **Settings → 關掉 "Generate Domain"**（bot 不需要 HTTP 端口）
5. **Variables** 頁面加入環境變數（見第 1 節）
6. Deploy 後確認 Logs：

```
🤖 FleetBot#1234 is online!
✅ Slash commands synced to guild xxxxxxxxx
Commands: /nb-add, /nb-list, /nb-done, /nb-weekly-sync, /nb-stats, /trend-scan
```

### Railway Free Tier 注意

- Trial plan: $5 credit/month（約 500 小時 lightweight bot）
- 此 bot 記憶體約 50-80MB，CPU 極低，每月約 $1-2
- Credit 用完暫停，下月自動恢復
- Railway Dashboard → Usage 監控用量

### 本地開發

```bash
# 安裝依賴
uv sync

# 本地跑（需要 .env）
uv run bot.py

# 加新套件
uv add httpx
uv add --dev pytest

# 記得 commit lock file
git add uv.lock pyproject.toml
git commit -m "chore: add dependency"
git push  # Railway 自動 redeploy
```

---

## 7. 與 Phase 3 OpenClaw Agent 的銜接

Notion DB schema 已對齊 Spec §7.2 SourceMonitor 的「素材庫」設計。Phase 3 遷移時：

1. `notion_add_source()` → 直接被 Agent 1 復用
2. `notion_query_sources()` → 被 Agent 2 DraftWriter 復用
3. `/nb-add` 保留為手動補充入口
4. 新增 Agent 1 的 RSS 自動偵測寫入同一個 DB

不需要重建 DB，只需要擴充 bot 或新增 agent。

---

## 8. 故障排除

| 問題 | 解決 |
|------|------|
| Slash commands 沒出現 | 確認 GUILD_ID 正確；重啟 bot |
| Notion 寫入失敗 | 確認 Integration 已 Connect 到 DB |
| URL 驗證失敗 | 確認 URL 以 `https://` 或 `http://` 開頭 |
| Bot 離線 | 檢查 Railway Logs；確認 credit 未用完 |
| Trend scan 無結果 | 確認 trendshift.io 可存取；檢查網路連線 |
| 每日掃描未觸發 | 確認 `TECHTREND_CHANNEL_ID` 已設定且 bot 有該頻道權限 |

### 自動重啟

Railway 設定 `restartPolicyType = "on_failure"`，crash 時自動重啟（最多 3 次）。持續 crash 請檢查 Railway Logs。

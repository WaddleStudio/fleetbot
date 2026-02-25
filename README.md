# NB Source Bot — 設定與使用指南

## 架構

```
Discord /nb-add 指令
        │
        ▼
  Python Bot (WSL/OpenClaw)
        │
        ▼
  Notion DB「NB 來源追蹤」
        │
        ▼ (每周一手動)
  NotebookLM + fleet-command repo
```

---

## 1. Notion DB 設定

在你現有的 Notion workspace 建立一個新 Database，屬性如下：

| 屬性名稱 | 類型 | 選項 |
|---------|------|------|
| **Title** | Title | （Notion 預設，不用改名） |
| **URL** | URL | — |
| **Notebook** | Select | `NB1`, `NB2`, `NB3`, `NB4` |
| **Note** | Rich Text | — |
| **Status** | Select | `pending`, `done`, `skipped` |
| **Added Date** | Date | — |
| **Synced Date** | Date | — |
| **Project** | Rich Text | — |

### 取得 Database ID
1. 在瀏覽器開啟該 DB 頁面
2. URL 格式：`https://notion.so/{workspace}/{database_id}?v=...`
3. 複製 `database_id`（32 字元，無 dash）
4. 確認你的 Integration 已被 **Connect** 到這個 DB

---

## 2. Discord Bot 設定

### 2.1 Discord Developer Portal
1. https://discord.com/developers/applications
2. 建立新 Application，命名為 `NB Source Bot`
3. 左側 **Bot** → 取得 Token
4. 左側 **OAuth2** → URL Generator：
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Attach Files`
5. 用生成的 URL 邀請 bot 到你的 server

### 2.2 取得 Guild ID
1. Discord 設定 → 進階 → 開啟「開發者模式」
2. 右鍵你的 server → 複製伺服器 ID

---

## 3. Railway 部署

### 3.1 建立 GitHub Repo

```bash
mkdir fleetbot && cd fleetbot
git init

# 複製 bot.py, pyproject.toml, Procfile, railway.toml, .python-version, .gitignore 到此目錄
# ⚠️ 不需要 requirements.txt，uv 用 pyproject.toml

# 初始化 uv + 生成 lock file
uv sync

# lock file 要 commit（確保 Railway 和本地一致）
git add .
git commit -m "feat: FleetBot v0.1 — nb-source tracking"
git remote add origin https://github.com/skywalker6666/fleetbot.git
git push -u origin main
```

### 3.2 Railway 設定

1. https://railway.app → New Project → Deploy from GitHub Repo
2. 選擇 `fleetbot` repo
3. Railway Nixpacks 會自動偵測 `pyproject.toml` + 安裝 uv
4. **Settings → Service → 關掉 "Generate Domain"**（bot 不需要 HTTP 端口）
5. **Variables** 頁面加入四個環境變數：

```
DISCORD_TOKEN=your_discord_bot_token
GUILD_ID=your_discord_server_id
NOTION_TOKEN=your_notion_integration_token
NOTION_DB_ID=your_notion_database_id
```

6. Deploy → 看 Logs 確認：

```
🤖 FleetBot#1234 is online!
✅ Slash commands synced to guild xxxxxxxxx
Commands: /nb-add, /nb-list, /nb-done, /nb-weekly-sync, /nb-stats
```

### 3.3 Railway Free Tier 注意事項

- Trial plan: $5 credit/month（約 500 小時 lightweight bot）
- 這個 bot 記憶體約 50-80MB，CPU 極低，一個月大概用 $1-2
- 如果 credit 用完會暫停，下個月自動恢復
- 可在 Railway Dashboard → Usage 監控用量

### 3.4 本地開發

```bash
# 安裝依賴
uv sync

# 本地跑（需要 .env）
uv run bot.py

# 加新套件
uv add httpx        # 例如未來要加 HTTP client
uv add --dev pytest # 開發依賴

# 記得 commit uv.lock
git add uv.lock pyproject.toml
git commit -m "chore: add httpx dependency"
git push  # Railway 自動 redeploy
```

---

## 4. 指令使用

### `/nb-add` — 記錄新來源
```
/nb-add nb:NB1 url:https://qwen.readthedocs.io/en/latest/ note:Qwen3 官方文件 project:RTA
```
- `nb`: 必填，選擇 NB1-NB4
- `url`: 必填，https:// 開頭
- `note`: 必填，簡述這是什麼
- `project`: 選填，關聯到哪個專案

### `/nb-list` — 查看清單
```
/nb-list scope:本周 pending     ← 預設
/nb-list scope:全部 pending
/nb-list scope:已完成（本周）
```

### `/nb-done` — 標記完成
```
/nb-done source_id:a1b2c3d4
```
- ID 從 `/nb-list` 取得（前 8 碼）

### `/nb-weekly-sync` — 匯出同步清單
輸出包含：
- 按 NB 分組的來源清單（含 checkbox）
- 純 URL 區塊（直接貼入 txt 文件）
- 同步 checklist

### `/nb-stats` — 統計面板
顯示各 NB 的 pending / done 數量。

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

## 6. 與 Phase 3 OpenClaw Agent 的銜接

這個 bot 的 Notion DB schema 已對齊 Spec §7.2 SourceMonitor 的「素材庫」設計。
Phase 3 遷移時：

1. `notion_add_source()` → 直接被 Agent 1 復用
2. `notion_query_sources()` → 被 Agent 2 DraftWriter 復用
3. `/nb-add` 保留為手動補充入口
4. 新增 Agent 1 的 RSS 自動偵測寫入同一個 DB

不需要重建 DB，只需要擴充 bot 或新增 agent。

---

## 7. 故障排除

| 問題 | 解決 |
|------|------|
| Slash commands 沒出現 | 確認 GUILD_ID 正確；重啟 bot |
| Notion 寫入失敗 | 確認 Integration 已 Connect 到 DB |
| URL 驗證失敗 | 確認 URL 以 `https://` 或 `http://` 開頭 |
| Bot 離線 | 檢查 Railway Logs；確認 credit 未用完 |

### 自動重啟
Railway 已設定 `restartPolicyType = "on_failure"`，crash 時會自動重啟（最多 3 次）。
如果持續 crash，檢查 Railway Logs 的錯誤訊息。

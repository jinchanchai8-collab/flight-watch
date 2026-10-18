# ✈️ 台灣出發 直飛低價 / 錯價機票監控 → LINE 推播

**每日日報**（早上 08:00）＋ **錯價快報**（每 2 小時檢查，只有發現新的 🚨 才推播）。排程由 **cron-job.org** 準時觸發，GitHub 內建排程（08:07／08:37／09:17）當備援，同一天不會重複推日報。

1. 從 **Travelpayouts / Aviasales API** 抓台北（桃園＋松山）、高雄出發，未來 6 個月的**直飛**票價
2. **篩選**：至少 7 天後出發；旅行天數依地區（日韓港澳東南亞 5–15 天、關島帛琉 4–10 天、歐美 10–30 天、杜拜 7–21 天、澳紐 8–21 天）
3. **每條航線跟自己同月份比**，算出便宜幾 %（不會只推亞洲、淡季不誤判）
4. **前 10 名、分散國家**：每國最多 2 筆、每區最多 4 筆、保留 2 個長程名額，錯價一律優先
5. 標示：🚨疑似錯價／🔥大降價（≥30%）／📉比平常便宜（≥15%）、⚠️樣本少、🧳廉航（附加 20kg 行李概估價）、🇹🇼台灣連假與需請假天數、🎌當地節日
6. **自我檢討**：疑似錯價 1～2 天內消失＝真錯價（該航線門檻調低）；3 天後還在＝淡季/常態促銷（門檻調高）
7. **💼 商務艙錯價**：商務艙價格 ≤ 同航線經濟艙一般價 × 1.5，或比商務艙一般價便宜 50% 以上
8. **🇹🇼 連假精選**：每個即將到來的台灣連假，列出涵蓋整段連假、最划算的直飛票與需請假天數；涵蓋連假的票在前 10 名排名中也會加分
9. 每筆票附 **👥 2 人總價**（廉航含行李）
10. 另掃 **Secret Flying** 錯價情報
11. **LINE 卡片式訊息**：每筆票一張卡片可左右滑動、按鈕直接開 Skyscanner；若 LINE 拒收卡片會自動改送文字版（`config.json` 的 `line_format` 改成 `text` 可固定用文字版）

手動執行時 Run workflow 的 mode 可選：`daily`（日報）、`preview`（預覽，不記錄已通知、可重複看）、`alert`（錯價快報）。

完全免費：GitHub Actions 免費排程、Travelpayouts 免費 API、LINE 官方帳號免費方案（每天 1 則，一個月約 30 則，遠低於免費額度）。

---

## 設定步驟（約 20 分鐘）

### 1. 申請 Travelpayouts API Token
1. 到 https://www.travelpayouts.com 註冊（免費，可用 Google 帳號）
2. 登入後台後，在 Programs（計畫）找到 **Aviasales** → Join
3. 後台右上角頭像 → **Profile** → **API token** 區塊，複製那串英數字

### 2. 建立 LINE 推播機器人（LINE Notify 已於 2025/3 停止服務，改用 Messaging API）
1. 到 https://manager.line.biz 用你的 LINE 帳號登入 → **建立 LINE 官方帳號**（免費方案，名稱隨意，例如「機票雷達」）
2. 進入該官方帳號 → 右上 **設定** → 左側 **Messaging API** → **啟用 Messaging API** → 建立／選擇一個 Provider
3. 同頁 **回應設定**：關掉「自動回應訊息」，避免它亂回話
4. 到 https://developers.line.biz/console → 點剛剛的 Provider → 點那個 channel：
   - **Basic settings** 分頁最下方 **Your user ID**（U 開頭一長串）→ 複製
   - **Messaging API** 分頁：用手機掃 QR code **把官方帳號加為好友**（沒加收不到）
   - 同分頁最下方 **Channel access token (long-lived)** → **Issue** → 複製

### 3. 放上 GitHub
1. 在 GitHub 建立一個 **Private** repository
2. 把這個資料夾所有檔案上傳（含 `.github/workflows/daily.yml`）
3. Repo → **Settings → Secrets and variables → Actions → New repository secret**，新增三個：

| Name | Value |
|---|---|
| `TRAVELPAYOUTS_TOKEN` | 第 1 步的 token |
| `LINE_CHANNEL_ACCESS_TOKEN` | 第 2 步的 channel access token |
| `LINE_USER_ID` | 第 2 步的 Your user ID |

4. **Actions** 分頁 → 若提示啟用就按啟用 → 選「每日機票監控」→ **Run workflow** 手動跑一次，LINE 應該會收到第一則日報

### 4. 設定準時排程（cron-job.org）
GitHub 內建排程常延遲或漏跑，所以改由 cron-job.org 準時呼叫 GitHub。

**4-1 產生 GitHub 金鑰（只能觸發這個倉庫的 Actions）**
1. GitHub 右上頭像 → **Settings** → 左側最下方 **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
2. Token name：`cron-job`；Expiration：選最長（1 年）
3. Repository access：**Only select repositories** → 選 `flight-watch`
4. Permissions → Repository permissions → **Actions** 設為 **Read and write**（其他不用動）
5. **Generate token** → 複製（`github_pat_` 開頭，只會顯示一次）

**4-2 在 cron-job.org 建兩個排程**
1. 到 https://cron-job.org 免費註冊 → 右上 Settings 把時區設為 **Asia/Taipei**
2. **Create cronjob**，兩個排程的共同設定：
   - URL：`https://api.github.com/repos/jinchanchai8-collab/flight-watch/actions/workflows/daily.yml/dispatches`
   - **Advanced** 分頁 → Request method：**POST**
   - Headers（按 Add 一行一行加）：
     - `Accept` = `application/vnd.github+json`
     - `Authorization` = `Bearer 你的github_pat_金鑰`
     - `X-GitHub-Api-Version` = `2022-11-28`
     - `Content-Type` = `application/json`
3. 排程 A「機票日報」：Execution schedule 每天 **08:00**；Request body：`{"ref":"main","inputs":{"mode":"auto-daily"}}`
4. 排程 B「錯價快報」：Execution schedule 每 **2 小時**；Request body：`{"ref":"main","inputs":{"mode":"alert"}}`
5. 每個排程建好後按 **Test run**，回應 **204** 就代表成功（GitHub Actions 會出現一筆新的執行）

| 回應碼 | 意思 |
|---|---|
| 204 | 成功 |
| 401 | 金鑰錯誤或過期 |
| 403 / 404 | 金鑰沒有選到 flight-watch 倉庫，或 Actions 權限不是 Read and write |
| 422 | Request body 格式錯，或 daily.yml 還沒更新 |

⚠️ 金鑰到期後排程會失效（回應 401），請重新產生並更新兩個排程的 Authorization。

---

## 調整條件（改 `config.json`）

| 欄位 | 說明 |
|---|---|
| `origins` | 出發機場，預設 TPE / KHH / RMQ |
| `months_ahead` | 往後監控幾個月 |
| `one_way` | `false` = 來回票價，`true` = 單程 |
| `regions.*.cities` | 要監控的城市代碼（只放有直飛的） |
| `ranking.top_n` | 每天推幾筆（預設 10） |
| `ranking.min_drop` | 至少比平常便宜多少才列入（預設 15%） |
| `ranking.min_samples` | 計算基準價最少需要幾筆資料 |
| `learning.default_error_cut` | 新航線的錯價門檻（預設 45%） |
| `learning.min_cut` / `max_cut` | 自我學習時門檻的上下限 |
| `learning.confirm_days` / `persist_days` | 幾天內消失算真錯價／幾天後還在算常態低價 |
| `dedupe_days` | 同一張票幾天內不重複推播 |
| `min_days_ahead` | 至少幾天後出發（預設 7） |
| `regions.*.trip_days` | 各地區旅行天數 [最短, 最長] |
| `diversity` | 每國／每區上限、長程保留名額 |
| `lcc.airlines` | 廉航代碼與單程 20kg 行李概估價 |
| `party.show_for` | 顯示幾人總價（0 = 不顯示） |
| `holiday_focus` | 連假加分、連假精選的數量與門檻 |
| `business` | 商務艙錯價判斷（與經濟艙倍數、降幅門檻、最多顯示幾筆） |

台灣連假與國外節日在 `holidays.json`，**每年底請更新下一年度**（人事行政總處通常 6 月公布）。

想改推播時間：改 `daily.yml` 的 cron（UTC 時間，台灣 = UTC+8）。

---

## 須知
- **價格是快取資料**（Aviasales 使用者近期搜尋過的價格），不是即時報價，可能已漲價或售完。錯價票通常幾小時內就會被修正，收到 🚨 請盡快點連結確認。
- 冷門航線可能幾天才有一筆資料，前幾天結果較少是正常的；歷史累積越久，「比平常便宜」的判斷越準。
- Skyscanner、Google Flights、Trip.com 等網站禁止爬蟲且會封鎖機器人，所以這裡用官方開放 API + 錯價情報 RSS，再附上 Skyscanner 連結讓你一鍵比價。
- 錯價票出票後航空公司有時會取消，建議先別訂不可退的飯店。
- 本機測試：`python flight_watch.py --dry-run`（只印不推）、`python flight_watch.py --test-line`（測 LINE 是否連通）

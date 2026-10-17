# ✈️ 台灣出發 直飛低價 / 錯價機票監控 → LINE 推播

每天早上 08:07（台灣時間）自動：

1. 從 **Travelpayouts / Aviasales API** 抓台北(TPE)、高雄(KHH)、台中(RMQ) 出發、未來 6 個月的**直飛**最低價
2. 從 **Secret Flying、Fly4free** 錯價情報 RSS 篩出台灣出發的特價／錯價
3. 依門檻 + 歷史價判斷，挑出：
   - 🚨 **疑似錯價**：低於區域 `error_price`，或低於歷史中位數的 50%
   - 🔥 **低價**：低於區域 `max_price`
   - 📉 **比平常便宜**：低於歷史中位數的 80%
4. 整理成一則訊息推到你的 LINE（附 Skyscanner 直飛搜尋連結，方便比價下單）

完全免費：GitHub Actions 免費排程、Travelpayouts 免費 API、LINE 官方帳號免費方案（每天 1 則，一個月約 30 則，遠低於免費額度）。

---

## 設定步驟（約 20 分鐘）

### 1. 申請 Travelpayouts API Token
1. 到 https://www.travelpayouts.com 註冊（免費）
2. 加入 **Aviasales** 計畫
3. 在 Profile → **API token** 複製 token

### 2. 建立 LINE 推播機器人（LINE Notify 已於 2025/3 停止服務，改用 Messaging API）
1. 到 https://developers.line.biz/console/ 用你的 LINE 帳號登入
2. 建立 Provider → 建立 **Messaging API** channel（會同時建一個 LINE 官方帳號）
3. **Basic settings** 頁最下方找到 **Your user ID**（U 開頭），複製
4. **Messaging API** 頁：
   - 用手機掃 QR code **把機器人加為好友**（沒加好友收不到）
   - 最下方 **Channel access token (long-lived)** → Issue → 複製
5. 建議到 LINE Official Account Manager 把「自動回應訊息」關掉，避免它亂回話

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

---

## 調整條件（改 `config.json`）

| 欄位 | 說明 |
|---|---|
| `origins` | 出發機場，預設 TPE / KHH / RMQ |
| `months_ahead` | 往後監控幾個月 |
| `one_way` | `false` = 來回票價，`true` = 單程 |
| `regions.*.cities` | 各區域要監控的城市代碼（只放有直飛的） |
| `regions.*.max_price` | 低於此價 → 🔥低價（新台幣） |
| `regions.*.error_price` | 低於此價 → 🚨疑似錯價 |
| `history_rules` | 累積 5 天以上歷史後，依中位數比例判斷 |
| `send_when_nothing_found` | 沒好票也要傳日報（確認程式還活著） |
| `dedupe_days` | 同一張票幾天內不重複推播 |

想改推播時間：改 `daily.yml` 的 cron（UTC 時間，台灣 = UTC+8）。

---

## 須知
- **價格是快取資料**（Aviasales 使用者近期搜尋過的價格），不是即時報價，可能已漲價或售完。錯價票通常幾小時內就會被修正，收到 🚨 請盡快點連結確認。
- 冷門航線可能幾天才有一筆資料，前幾天結果較少是正常的；歷史累積越久，「比平常便宜」的判斷越準。
- Skyscanner、Google Flights、Trip.com 等網站禁止爬蟲且會封鎖機器人，所以這裡用官方開放 API + 錯價情報 RSS，再附上 Skyscanner 連結讓你一鍵比價。
- 錯價票出票後航空公司有時會取消，建議先別訂不可退的飯店。
- 本機測試：`python flight_watch.py --dry-run`（只印不推）、`python flight_watch.py --test-line`（測 LINE 是否連通）

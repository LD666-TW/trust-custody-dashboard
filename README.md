# 境內基金保管市場看板（自己在電腦上看）

這是課程 Demo 1 的本機看板。資料取自投信投顧公會公開資料；**每月更新，非即時**。首頁顯示最新月份；2026/08 等舊月份會保留，可隨時切換。

## 打開看板

在 `public` 資料夾啟動本機預覽：

```bash
cd public
python3 -m http.server 8000 --bind 127.0.0.1
```

然後用這台電腦的瀏覽器開 `http://localhost:8000/`。關掉終端機或重新開機後，預覽服務會停止；需要再啟動一次。網址只在這台電腦有效，不會公開到網路。

## 每天自動更新如何運作

1. GitHub Actions 每天約台北時間 10:17 執行一次。
2. 先對公會兩份 CSV 各讀取 1 byte 與更新時間。**兩份都沒變時，不下載完整檔案，也不改看板。**如果公會不提供可靠的更新時間，就下載檔案直接確認月份。
3. 兩份開放資料都變成同一個新月份後，下載完整資料與 SITCA 兩份報表，合併、重算與檢查。任一必要檢查失敗，就保留舊資料並讓該次 GitHub 執行顯示失敗。
4. 檢查通過才把新月份原始檔與看板資料存回私人 GitHub 儲存庫。
5. 這台 Mac 每小時從 GitHub 同步一次。Mac 必須開機、連網；睡眠時不會執行，醒來後的下一次排程會再同步。重新載入看板頁面即可讀到已同步的資料。

不需要 Vercel。GitHub 上保存的是程式和公會公開資料；私人儲存庫不會自動變成公開網站。

## 第一次設定

目前儲存庫預期放在個人 GitHub 帳號底下，設為 **Private**。推送完成後，在 GitHub 儲存庫的 **Settings → Actions → General → Workflow permissions** 確認允許寫入。工作流程自身已要求 `contents: write`，但儲存庫設定若限制權限，仍會擋住自動提交。

本機同步安裝：

```bash
./install-local-sync.sh
```

同步會在安裝時立即執行一次，此後每小時一次。也可以隨時手動執行 `./sync-local.sh`。紀錄在 `~/Library/Logs/trust-dashboard-sync.log`。

GitHub 上可到 **Actions → 每月資料更新 → Run workflow** 手動測試。若公會資料未變，應顯示「兩份公會檔案的更新時間都未變」，不會提交資料。

## 月份顯示

- 首頁預設顯示最新月份：`public/data/index.json` 的 `pinned` 為空字串 `""`。
- 臨時看其他已保存月份：網址加 `?month=202609`。
- 想固定顯示某個月份：把 `pinned` 改成該月份（例如 `"202608"`），提交並推送到 GitHub。

## 本機驗證與重算

```bash
python3 tests/acceptance_202608.py
python3 pipeline/build_data.py --month 202608 --offline
python3 pipeline/build_data.py --mode auto
```

離線驗收必須與簡報 Demo 1 的 31 項數字相符。原始檔保存在 `data/raw/<年月>/`，每月結果在 `public/data/<年月>.json`。

## 資料來源與限制

- [公會境內基金基本資料](https://data.gov.tw/dataset/43476)
- [公會境內基金各項費用資料](https://data.gov.tw/dataset/46443)
- [SITCA 基金基本資料表](https://www.sitca.org.tw/ROC/Industry/IN2105.aspx)：標準與費率銀行兩種欄位

只含目前仍存續的基金，且只看國內保管行。不同級別以基金統編歸為一檔；新基金成立日使用基金層級日期。基金客戶資料與 Demo 2 業務分群不在看板內。

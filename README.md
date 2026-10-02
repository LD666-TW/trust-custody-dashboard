# 境內基金保管市場看板

課程 Demo 1 的線上看板，使用投信投顧公會公開資料，**每月更新，非即時**。上線後網址為 `https://ld666-tw.github.io/trust-custody-dashboard/`。首頁顯示最新月份；舊月份也會保留。

## 自動更新

1. GitHub Actions 每天約台北時間 10:17 檢查公會兩份 CSV 的更新時間。兩份都沒變時，不下載完整檔案。
2. 兩份開放資料都出現同一個新月份後，下載完整資料及 SITCA 兩份報表，合併、重算並執行資料品質檢查。
3. 檢查通過才將新月份原始檔與看板 JSON 提交到 GitHub，隨即在**同一次工作流程**發布 GitHub Pages。檢查失敗會保留舊版並讓工作流程失敗。
4. 手動修改看板頁面並推送到 `main` 時，另一個工作流程會重新發布 Pages。

GitHub Pages 的網址可由任何人開啟。看板只使用公會公開資料，不含客戶檔與 Demo 2 業務分群。頁面設有 `noindex` 標籤，但這不等於密碼保護。

## 月份顯示

- 首頁預設顯示最新月份：`public/data/index.json` 的 `pinned` 為空字串 `""`。
- 查看已保存的舊月份：網址加 `?month=202608`。
- 想固定顯示某個月份：把 `pinned` 改成該月份並推送。

## 本機驗證

```bash
python3 tests/acceptance_202608.py
python3 pipeline/build_data.py --mode auto
```

2026/08 的驗收必須與簡報 Demo 1 的 31 項數字相符。每月原始檔保存在 `data/raw/<年月>/`，看板資料在 `public/data/<年月>.json`。

## 資料來源與口徑

- [公會境內基金基本資料](https://data.gov.tw/dataset/43476)
- [公會境內基金各項費用資料](https://data.gov.tw/dataset/46443)
- [SITCA 基金基本資料表](https://www.sitca.org.tw/ROC/Industry/IN2105.aspx)：標準與費率銀行兩種欄位

只含目前仍存續的基金，且只看國內保管行。不同級別以基金統編歸為一檔；新基金成立日使用基金層級日期。

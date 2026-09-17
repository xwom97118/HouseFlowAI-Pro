# 3.1.1 Universal Import SSL fix

- 修正「匯入單一物件網址」在 Python 3.14 對缺少 Subject Key
  Identifier 的憑證鏈（例如 buy.yungching.com.tw）觸發
  SSLCertVerificationError 的問題。整店同步先前已經用
  RelaxedTLSAdapter 解決過同一個問題，現在抽成共用元件
  app/services/http_client.py，單一物件匯入與整店同步共用同一套
  certifi CA / SSL / retry / connection pooling 設定，不使用
  verify=False。
- 單一物件匯入新增 Playwright fallback（HTTP 抓不到或資料太少時，
  改用 HouseFlow 隨附的 Chromium 渲染），並在單一物件匯入情境下
  重複使用同一個瀏覽器行程，不必每次匯入都重新啟動；整店同步的
  Playwright fallback（多執行緒併發）維持原本各自獨立啟動，避免
  跨執行緒共用瀏覽器造成的執行緒安全風險。
- 單一物件匯入改為背景 QThread 執行，畫面顯示「正在讀取物件頁面…
  → 正在解析物件資料… → 正在下載照片… → 匯入完成」，不再卡住畫面。
- 重複匯入同一網址會更新既有物件，不會產生重複物件。

# 3.1 Sync Center

- 新增獨立「同步中心」頁面：管理多個同步來源、立即同步、同步歷史。
- 新增 sync_sources / sync_runs / property_changes 資料表，向下相容既有資料。
- 增量同步：自動辨識新增、價格異動、其他內容異動、下架、重新上架。
- 下架安全判定：單次同步不會把來源內大多數物件誤標下架。
- 整店同步、物件中心手動同步改為背景執行緒，不再卡住畫面。
- 物件同步新增儲存物件類型、社區、特色欄位（先前抓到卻沒有寫入資料庫）。
- 修正封裝後 EXE 找不到 Playwright Chromium 的問題：改用隨程式發行的
  pw-browsers 資料夾，不再依賴開發機器的個人快取路徑。

# 2.0.1

- 修正 Windows 啟動 BAT，移除中文檔名與編碼問題。
- 收藏與取消收藏按鈕正式連接。
- 標籤、備註永久寫入 SQLite。
- 物件中心與頂部皆可返回 Dashboard。
- 新增收藏篩選與列表顯示。
- 新增可實際新增、編輯、刪除的 CRM。
- 新增「龍潭成交策略」產生與歷史保存。
- AI 預設關閉，避免 API 額度錯誤。
- 保留原有 30 筆物件資料庫。

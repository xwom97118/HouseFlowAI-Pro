# License PostgreSQL Backup Strategy

> Phase 3A（2026-09-23，規格第 16 節）。這份文件是**架構與流程規劃**
> ——這一輪不會真的建立任何付費備份服務，因為還沒有真正的 Render
> PostgreSQL 資料庫存在。等 Phase 3B 真的建好資料庫之後，照這裡的
> 流程設定即可。

## 1. 為什麼需要

部署後，License PostgreSQL 裡的資料是真正的商業重要資料：

- `licenses`：每一筆付費訂閱、試用、Early Bird 定價鎖定。
- `device_bindings`：裝置綁定關係。
- `trial_fingerprints`：試用資格記錄（防重複試用）。
- `admin_audit_logs`：誰在什麼時候做了什麼操作的完整記錄。
- `admin_users`/`admin_sessions`：Admin 帳號本身。

這些資料遺失，不只是技術問題，是直接的營收/客戶關係問題（客戶已經
付費的訂閱記錄不見了）。

**跟 Desktop 端的 Backup（`app/services/backup_service.py`，Phase 1）
是兩個完全獨立的系統**：Desktop 端備份的是使用者的物件/CRM/排程
資料，留在使用者自己的電腦上；這裡講的是 License Server 那一份
PostgreSQL，兩者不會、也不應該互相依賴或共用備份機制（License Server
從架構上就沒有、也不應該有使用者的業務資料，見
[LICENSE_SECURITY.md](LICENSE_SECURITY.md) 第 9 節）。

## 2. Backup

### 2.1 Render 內建的自動備份

Render 的 PostgreSQL（Starter 以上方案）內建每日自動備份，保留
一定天數（依方案而定，見 Render 官方文件——Phase 3B 建立資料庫時
確認當時的實際保留天數）。這是**第一層、預設就有**的保護，不需要
額外設定。

### 2.2 額外的邏輯備份（建議，Phase 3B 決定是否啟用）

除了 Render 內建的機制，建議額外設定一個定期跑 `pg_dump` 的排程
（例如 Render 的 Cron Job，或外部排程服務），把邏輯備份（SQL dump）
存到一個獨立的物件儲存（例如 S3 相容服務）。理由：

- Render 內建備份是「資料庫層級」的快照，邏輯備份（`pg_dump`）是
  「人類看得懂、可以單獨還原單一張表」的格式，兩者互補。
- 邏輯備份存在**不同的服務商**，避免「Render 帳號本身出問題」這種
  單點故障連備份都一起沒了。

這一輪不建立任何真正的排程或付費儲存空間——只是記錄下建議的架構，
留給 Phase 3B 決定要不要做、什麼時候做。

## 3. Restore（還原）

### 3.1 從 Render 內建備份還原

Render Dashboard → 該 PostgreSQL 資料庫 → Backups → 選一個時間點 →
Restore。Render 會建立一個新的資料庫（不會直接覆蓋現有的），還原
完成後需要手動把 Web Service 的 `DATABASE_URL` 切換過去。

### 3.2 從邏輯備份（`pg_dump`）還原

```bash
psql "$DATABASE_URL" < backup.sql
```

還原前務必：

1. 確認要還原的目標資料庫是**新建立的空資料庫**，不是正在服務中的
   那一個（避免部分還原造成資料混亂）。
2. 還原完成後跑 `python server/run_migrations.py`，確認
   `alembic_version` 記錄的版本跟 migration 檔案裡最新的版本一致
   （邏輯備份的時間點可能早於某次 migration，需要補跑）。

## 4. Verification（驗證備份真的可用）

備份「存在」不等於備份「可用」——常見的失敗模式是備份檔案本身壞掉、
或還原流程本身有問題，直到真的需要用的時候才發現。建議（Phase 3B
決定實際頻率）：

- 至少每季一次，把最近一份備份還原到一個全新、獨立的測試資料庫
  （不影響正式環境），確認：
  - 還原本身沒有報錯
  - 關鍵表的列數符合預期量級（不是 0，也不是異常暴增/減少）
  - 跑一次 `server/tests/` 裡的 server 測試（指向這個還原出來的
    資料庫），確認 schema 完整、application 邏輯可以正常操作這份
    還原出來的資料

## 5. Retention（保留政策）

| 類型 | 保留天數 |
|---|---|
| Render 內建自動備份 | 依 Render 方案而定，Phase 3B 建立資料庫時確認 |
| 邏輯備份（如果啟用） | 建議至少 30 天，配合 `admin_audit_logs` 本身作為長期稽核記錄 |

`admin_audit_logs` 本身**不會**過期清除（目前沒有任何自動刪除舊
Audit Log 的機制——這是刻意的，Audit Log 的價值就在於完整的歷史
記錄）。

## 6. Disaster Recovery（重大故障情境）

| 情境 | 應對 |
|---|---|
| PostgreSQL 資料庫本身損毀/無法連線 | 從 Render 內建備份還原到新資料庫，切換 `DATABASE_URL`，重新部署 Web Service |
| 整個 Render 帳號/服務無法使用 | 從獨立儲存的邏輯備份，在新的 Render 帳號（或其他 PostgreSQL 服務）重建，重新設定所有環境變數（見 [PRODUCTION_ENVIRONMENT.md](PRODUCTION_ENVIRONMENT.md)），**簽章私鑰必須維持不變**（否則所有 Desktop 端快取的簽章會全部驗證失敗，見 [CLOUD_SECURITY.md](CLOUD_SECURITY.md) 第 4 節）——這代表簽章私鑰本身也需要獨立、安全地備份，不能只存在 Render 的環境變數裡（Phase 3B 決定實際的 secret 備份/託管方式，例如密碼管理器） |
| Admin 帳號全部無法登入 | 需要直接連線資料庫（`psql`）手動處理，或走 `server/bootstrap_admin.py` 建立新帳號（前提是資料庫本身可連線） |

## 7. 這一輪明確沒有做的事

- 沒有建立任何真正的付費備份服務或排程。
- 沒有真的執行過一次還原演練（架構規劃完成，實際執行是 Phase 3B
  的工作，見 [PHASE3B_DEPLOY_CHECKLIST.md](PHASE3B_DEPLOY_CHECKLIST.md)）。
- 沒有決定邏輯備份要存在哪個物件儲存服務（留給 Phase 3B 依當時的
  成本/需求決定）。

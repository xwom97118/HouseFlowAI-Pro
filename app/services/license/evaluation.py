"""License 狀態的純邏輯運算（2026-09-21 產品化 Phase 1，規格第 15～16
節：offline grace + clock-tamper 防護、到期不刪資料）。

刻意獨立成一個不依賴任何 I/O、不依賴任何後端的純函式模組——
MockLicenseProvider 跟未來真正的 Cloud LicenseProvider 都呼叫這裡的
evaluate_license()，離線寬限期／時鐘回撥偵測的規則只寫一份，不會
「本機一套邏輯、雲端又是另一套邏輯」兩邊長歪。
"""
from __future__ import annotations

from datetime import datetime

from app.services.license.models import (
    License,
    LicenseCheckResult,
    LicenseStatus,
    days_between,
    parse_iso,
)

OFFLINE_GRACE_DAYS_DEFAULT = 7


def evaluate_license(
    license_: License | None,
    now: datetime,
    last_verified_at: datetime | None,
    high_water_mark: datetime | None,
    offline_grace_days: int = OFFLINE_GRACE_DAYS_DEFAULT,
) -> LicenseCheckResult:
    """計算「現在」這一刻，這個使用者可不可以用 HouseFlow。

    參數：
    - license_：目前這台裝置綁定的 License（可能是 None——還沒開始
      試用、也還沒啟用）。
    - now：目前系統時間（呼叫端傳入，方便測試；正式執行時就是
      datetime.now()）。
    - last_verified_at：上一次成功跟 LicenseService 對過的時間點
      （Trial/Mock provider 是本機時間；未來真正 Cloud provider 應該
      是「伺服器回應裡的時間戳記」，不是純粹的本機時間，這樣才能真正
      防止「使用者自己調本機時鐘」——這個參數的來源品質由呼叫端負責，
      這裡只負責用它做離線寬限期計算）。
    - high_water_mark：本機看過的最新時間戳記（每次任何一次成功
      verification／app 啟動都要更新並持久化）。如果 now 明顯早於
      high_water_mark，代表系統時鐘被往回調過——不是崩潰性拒絕使用
      （不做侵入式 DRM），而是不採信「離線寬限期還沒過」這個判斷，
      要求重新連網驗證。

    回傳的 LicenseCheckResult 已經把「to-do 給 UI 顯示什麼」都算好，
    UI 層不需要重算到期日邏輯。
    """
    clock_tampered = high_water_mark is not None and now < high_water_mark

    if license_ is None:
        return LicenseCheckResult.blocked(
            LicenseStatus.EXPIRED,
            "尚未開始試用，也還沒有有效的 License。",
        )

    if license_.status == LicenseStatus.SUSPENDED:
        return LicenseCheckResult.blocked(
            LicenseStatus.SUSPENDED,
            "這組 License 已被停權，請聯絡 HouseFlow 客服。",
        )

    if license_.status == LicenseStatus.TRIAL:
        trial_ends = parse_iso(license_.trial_ends_at)
        if trial_ends is None:
            return LicenseCheckResult.blocked(LicenseStatus.EXPIRED, "試用資料不完整，請重新啟動 HouseFlow。")
        if now >= trial_ends:
            return LicenseCheckResult.blocked(
                LicenseStatus.EXPIRED,
                "7 天免費試用已結束，請輸入 License Key 或訂閱 HouseFlow Professional。",
            )
        remaining = days_between(now, trial_ends)
        return LicenseCheckResult.allowed(
            LicenseStatus.TRIAL,
            f"試用中，剩餘 {remaining} 天。",
            days_remaining=remaining,
        )

    if license_.status == LicenseStatus.ACTIVE:
        expires_at = parse_iso(license_.expires_at)
        if expires_at is None:
            return LicenseCheckResult.blocked(LicenseStatus.EXPIRED, "License 到期資料不完整，請重新驗證。")

        if now < expires_at:
            remaining = days_between(now, expires_at)
            return LicenseCheckResult.allowed(
                LicenseStatus.ACTIVE,
                f"HouseFlow Professional 使用中，訂閱剩餘 {remaining} 天。",
                days_remaining=remaining,
            )

        # 已經過了 expires_at：看能不能用 offline grace 續命。
        if clock_tampered or last_verified_at is None:
            return LicenseCheckResult.blocked(
                LicenseStatus.EXPIRED,
                "HouseFlow 訂閱已到期，且無法確認離線寬限期是否有效，請連網重新驗證。",
            )

        offline_elapsed_days = (now - last_verified_at).total_seconds() / 86400
        if offline_elapsed_days <= offline_grace_days:
            offline_remaining = max(0, int(offline_grace_days - offline_elapsed_days))
            return LicenseCheckResult.allowed(
                LicenseStatus.ACTIVE,
                f"目前離線中，寬限期還剩 {offline_remaining} 天，請盡快連網完成授權驗證。",
                is_offline_grace=True,
                offline_days_remaining=offline_remaining,
            )

        return LicenseCheckResult.blocked(
            LicenseStatus.EXPIRED,
            f"離線已超過 {offline_grace_days} 天寬限期，請連網重新驗證 License。",
        )

    return LicenseCheckResult.blocked(LicenseStatus.EXPIRED, "HouseFlow 訂閱已到期，請續訂或重新驗證。")

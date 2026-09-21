"""本機 / 開發用 LicenseService 實作（2026-09-21 產品化 Phase 1）。

這不是「假資料 demo」——這是這一輪唯一會真正接進 Desktop app 的
LicenseService 實作，讓 HouseFlow 在還沒有真正的 License Cloud 之前
就能完整跑過 Trial／Activation／到期／離線寬限期的所有 UI 流程。

儲存方式：透過呼叫端注入的 get_setting/set_setting（通常是
Database.get_setting/set_setting，key 都加上 license_ 前綴，跟其他
app_settings 放在同一張表），不另外開一個 SQLite 檔案——單一裝置
只有一組 License 狀態，不需要獨立的 table。

未來要換成真正打 HouseFlow License Cloud 的 provider 時，只需要新增
一個同樣實作 LicenseService 介面的類別，MainWindow／Settings 頁面
完全不用改（依賴注入在 app 啟動時決定用哪個 provider）。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Callable

from app.services.license.evaluation import OFFLINE_GRACE_DAYS_DEFAULT, evaluate_license
from app.services.license.models import (
    DeviceStatus,
    License,
    LicenseCheckResult,
    LicensePlan,
    LicenseStatus,
    parse_iso,
)
from app.services.license.service import (
    DeviceLimitReachedError,
    LicenseService,
    TrialAlreadyUsedError,
)

_KEY_PREFIX = "license_"
_STATE_KEY = f"{_KEY_PREFIX}state_json"
_HIGH_WATER_MARK_KEY = f"{_KEY_PREFIX}high_water_mark"
_USED_TRIAL_FINGERPRINTS_KEY = f"{_KEY_PREFIX}trial_used_fingerprints"

TRIAL_DAYS_DEFAULT = 7


class MockLicenseProvider(LicenseService):
    def __init__(
        self,
        get_setting: Callable[[str, str], str],
        set_setting: Callable[[str, str], None],
        now_provider: Callable[[], datetime] = datetime.now,
        trial_days: int = TRIAL_DAYS_DEFAULT,
        offline_grace_days: int = OFFLINE_GRACE_DAYS_DEFAULT,
        current_price: int = 688,
    ) -> None:
        self._get_setting = get_setting
        self._set_setting = set_setting
        self._now = now_provider
        self.trial_days = trial_days
        self.offline_grace_days = offline_grace_days
        self.current_price = current_price

    # ------------------------------------------------------------------
    # 內部儲存：一整組 License 狀態存成一個 JSON blob（單一裝置只有一組，
    # 不需要多筆記錄的關聯式結構）。
    # ------------------------------------------------------------------

    def _load_state(self) -> dict | None:
        raw = self._get_setting(_STATE_KEY, "").strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def _save_state(self, state: dict) -> None:
        self._set_setting(_STATE_KEY, json.dumps(state, ensure_ascii=False))

    def _state_to_license(self, state: dict) -> License:
        return License(
            license_id=state["license_id"],
            license_key_hash=state.get("license_key_hash", ""),
            plan=LicensePlan(state.get("plan", LicensePlan.PROFESSIONAL.value)),
            status=LicenseStatus(state["status"]),
            trial_started_at=state.get("trial_started_at"),
            trial_ends_at=state.get("trial_ends_at"),
            activated_at=state.get("activated_at"),
            expires_at=state.get("expires_at"),
            is_early_bird=bool(state.get("is_early_bird", False)),
            locked_price=state.get("locked_price"),
            currency=state.get("currency", "TWD"),
            device_limit=int(state.get("device_limit", 1)),
            created_at=state.get("created_at", ""),
            updated_at=state.get("updated_at", ""),
        )

    def _update_high_water_mark(self, now: datetime) -> None:
        current = parse_iso(self._get_setting(_HIGH_WATER_MARK_KEY, ""))
        if current is None or now > current:
            self._set_setting(_HIGH_WATER_MARK_KEY, now.isoformat())

    def _high_water_mark(self) -> datetime | None:
        return parse_iso(self._get_setting(_HIGH_WATER_MARK_KEY, ""))

    def _last_verified_at(self) -> datetime | None:
        return parse_iso(self._get_setting(f"{_KEY_PREFIX}last_verified_at", ""))

    def _set_last_verified_at(self, now: datetime) -> None:
        self._set_setting(f"{_KEY_PREFIX}last_verified_at", now.isoformat())

    def _used_trial_fingerprints(self) -> set[str]:
        raw = self._get_setting(_USED_TRIAL_FINGERPRINTS_KEY, "").strip()
        if not raw:
            return set()
        try:
            return set(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            return set()

    def _mark_trial_used(self, device_fingerprint: str) -> None:
        used = self._used_trial_fingerprints()
        used.add(device_fingerprint)
        self._set_setting(_USED_TRIAL_FINGERPRINTS_KEY, json.dumps(sorted(used)))

    # ------------------------------------------------------------------
    # LicenseService 介面
    # ------------------------------------------------------------------

    def start_trial(self, device_fingerprint: str, device_name: str) -> License:
        # 見規格第 14 節：同一裝置原則上只能取得一次免費試用——這裡的
        # 「裝置」是本機持久化的 device_fingerprint（見 fingerprint.py），
        # 不是靠刪 SQLite 就能重置的東西；最終要防止「重灌 HouseFlow」
        # 濫用試用資格，仍然需要伺服器端記錄（見規格說明），這裡先在
        # 本機記一份已使用清單，作為最小可行版本。
        if device_fingerprint in self._used_trial_fingerprints():
            raise TrialAlreadyUsedError("這台裝置已經使用過免費試用。")

        now = self._now()
        trial_ends = now + timedelta(days=self.trial_days)
        state = {
            "license_id": f"trial-{uuid.uuid4().hex[:12]}",
            "license_key_hash": "",
            "plan": LicensePlan.PROFESSIONAL.value,
            "status": LicenseStatus.TRIAL.value,
            "trial_started_at": now.isoformat(),
            "trial_ends_at": trial_ends.isoformat(),
            "activated_at": None,
            "expires_at": None,
            "is_early_bird": False,
            "locked_price": None,
            "currency": "TWD",
            "device_limit": 1,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "device_fingerprint": device_fingerprint,
            "device_name": device_name,
        }
        self._save_state(state)
        self._mark_trial_used(device_fingerprint)
        self._update_high_water_mark(now)
        self._set_last_verified_at(now)
        return self._state_to_license(state)

    def activate_license(self, license_key: str, device_fingerprint: str, device_name: str) -> License:
        # Mock provider 沒有真正的 license key 資料庫可查——這裡只做
        # 「格式看起來像 HF-PRO-XXXX-XXXX-XXXX」的檢查，任何格式正確的
        # key 都會成功啟用成一組 12 個月 Professional License，純粹
        # 用來讓 Desktop 端的啟用流程／UI／測試可以完整跑一遍。真正的
        # key 有效性驗證屬於未來 Cloud provider 的責任。
        normalized = license_key.strip().upper()
        if not normalized.startswith("HF-PRO-") or len(normalized.split("-")) != 5:
            raise LookupError("License Key 格式不正確，請確認是否貼上完整的 HF-PRO-XXXX-XXXX-XXXX。")

        existing = self._load_state()
        if existing and existing.get("status") == LicenseStatus.ACTIVE.value:
            bound_fingerprint = existing.get("device_fingerprint")
            if bound_fingerprint and bound_fingerprint != device_fingerprint:
                raise DeviceLimitReachedError(
                    "這組 License 已經綁定在另一台裝置，請先請 Admin 解除舊裝置的綁定。"
                )

        now = self._now()
        expires_at = now + timedelta(days=30)
        state = {
            "license_id": f"lic-{uuid.uuid4().hex[:12]}",
            "license_key_hash": _hash_key(normalized),
            "plan": LicensePlan.PROFESSIONAL.value,
            "status": LicenseStatus.ACTIVE.value,
            "trial_started_at": None,
            "trial_ends_at": None,
            "activated_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "is_early_bird": False,
            "locked_price": self.current_price,
            "currency": "TWD",
            "device_limit": 1,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "device_fingerprint": device_fingerprint,
            "device_name": device_name,
        }
        self._save_state(state)
        self._update_high_water_mark(now)
        self._set_last_verified_at(now)
        return self._state_to_license(state)

    def get_current_license(self) -> License | None:
        state = self._load_state()
        return self._state_to_license(state) if state else None

    def check_license(self, device_fingerprint: str) -> LicenseCheckResult:
        state = self._load_state()
        license_ = self._state_to_license(state) if state else None
        now = self._now()

        if license_ is not None and state is not None:
            bound_fingerprint = state.get("device_fingerprint")
            if bound_fingerprint and bound_fingerprint != device_fingerprint:
                return LicenseCheckResult.blocked(
                    license_.status,
                    "這台裝置跟目前 License 綁定的裝置不符，請重新啟用或聯絡客服解除舊裝置綁定。",
                )
            # 「連得上」就當作一次成功 verification（mock provider 沒有
            # 真正的網路呼叫，這裡直接視為每次呼叫都連得上；真正的
            # Cloud provider 應該只在成功打到伺服器時才更新這個時間戳記）。
            self._set_last_verified_at(now)

        self._update_high_water_mark(now)

        return evaluate_license(
            license_,
            now=now,
            last_verified_at=self._last_verified_at(),
            high_water_mark=self._high_water_mark(),
            offline_grace_days=self.offline_grace_days,
        )

    # ------------------------------------------------------------------
    # 測試／開發用工具：允許測試直接把狀態改成 Expired/Suspended 等，
    # 不用真的等 30 天。正式的 Cloud provider 不會有這些方法。
    # ------------------------------------------------------------------

    def _force_status_for_testing(self, status: LicenseStatus, **overrides) -> None:
        state = self._load_state() or {}
        state["status"] = status.value
        state.update(overrides)
        self._save_state(state)


def _hash_key(license_key: str) -> str:
    import hashlib

    return hashlib.sha256(license_key.encode("utf-8")).hexdigest()

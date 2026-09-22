"""HTTP License Provider（2026-09-22 Phase 2，規格第 20 節）：Desktop
端「正式」的 LicenseService 實作，呼叫本機／未來正式的 License
Server。MockLicenseProvider 繼續保留給測試使用（見
mock_provider.py 檔案開頭的說明）。

離線容忍設計：check_license() 會先嘗試真的打一次
POST /api/license/verify；連不上（httpx 的連線/逾時例外）時，退回
使用「上一次成功驗證後快取在本機的狀態」跑
app.services.license.evaluation.evaluate_license()——跟
MockLicenseProvider 的離線寬限期判斷是同一套純函式，只是這裡的
last_verified_at 是「真正連上 server 那一刻」而不是「每次呼叫都算
成功」，因此離線寬限期在這裡才有實質意義（見規格第 9 節）。

本機快取全部走跟 MockLicenseProvider 同一組 app_settings key（
license_state_json / license_high_water_mark /
license_last_verified_at），保證 Settings 頁「授權資訊」面板不需要
知道目前用的是哪一個 provider。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Callable

import httpx

from app.services.license.evaluation import OFFLINE_GRACE_DAYS_DEFAULT, evaluate_license
from app.services.license.models import (
    License,
    LicenseCheckResult,
    LicensePlan,
    LicenseStatus,
    parse_iso,
)
from app.services.license.service import (
    DeviceLimitReachedError,
    LicenseError,
    LicenseService,
    TrialAlreadyUsedError,
)
from app.version import APP_VERSION

_KEY_PREFIX = "license_"
_STATE_KEY = f"{_KEY_PREFIX}state_json"
_HIGH_WATER_MARK_KEY = f"{_KEY_PREFIX}high_water_mark"

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 5.0

_CONNECTION_ERROR_MESSAGE = "無法連線到 HouseFlow License Server，請檢查網路連線後再試一次。"


class HTTPLicenseProvider(LicenseService):
    def __init__(
        self,
        get_setting: Callable[[str, str], str],
        set_setting: Callable[[str, str], None],
        base_url: str = DEFAULT_BASE_URL,
        now_provider: Callable[[], datetime] = datetime.now,
        offline_grace_days: int = OFFLINE_GRACE_DAYS_DEFAULT,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self._get_setting = get_setting
        self._set_setting = set_setting
        self._base_url = base_url.rstrip("/")
        self._now = now_provider
        self.offline_grace_days = offline_grace_days
        self._timeout = timeout
        self._client_factory = client_factory or (lambda: httpx.Client(timeout=self._timeout))

    # ------------------------------------------------------------------
    # 本機快取（跟 MockLicenseProvider 共用同一組 key）
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
            license_id=state.get("license_id", ""),
            license_key_hash="",  # HTTP provider 從不持有明文 key 或 server 端的 hash
            plan=LicensePlan(state.get("plan") or LicensePlan.PROFESSIONAL.value),
            status=LicenseStatus(state["status"]),
            trial_started_at=state.get("trial_started_at"),
            trial_ends_at=state.get("trial_ends_at"),
            activated_at=state.get("activated_at"),
            expires_at=state.get("expires_at"),
            is_early_bird=bool(state.get("is_early_bird", False)),
            locked_price=state.get("price") if state.get("is_early_bird") else None,
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

    def _cache_server_response(self, data: dict) -> None:
        now = self._now()
        state = {
            "license_id": data.get("license_id"),
            "plan": data.get("plan"),
            "status": data.get("status"),
            "is_early_bird": data.get("is_early_bird", False),
            "price": data.get("price"),
            "currency": data.get("currency", "TWD"),
            "trial_ends_at": data.get("trial_ends_at"),
            "expires_at": data.get("expires_at"),
        }
        self._save_state(state)
        self._set_last_verified_at(now)
        self._update_high_water_mark(now)

    # ------------------------------------------------------------------
    # HTTP 呼叫
    # ------------------------------------------------------------------

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base_url}{path}"
        try:
            with self._client_factory() as client:
                response = client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise LicenseError(_CONNECTION_ERROR_MESSAGE) from exc

        if response.status_code >= 500:
            raise LicenseError("License Server 發生錯誤，請稍後再試。")
        return {"status_code": response.status_code, "body": _safe_json(response)}

    # ------------------------------------------------------------------
    # LicenseService 介面
    # ------------------------------------------------------------------

    def start_trial(self, device_fingerprint: str, device_name: str) -> License:
        result = self._post(
            "/api/trial/start",
            {"device_fingerprint": device_fingerprint, "device_name": device_name, "app_version": APP_VERSION},
        )
        if result["status_code"] == 409:
            raise TrialAlreadyUsedError(result["body"].get("detail", "這台裝置已經使用過免費試用。"))
        if result["status_code"] >= 400:
            raise LicenseError(result["body"].get("detail", "開始試用失敗。"))

        self._cache_server_response(result["body"])
        return self._state_to_license(self._load_state())

    def activate_license(self, license_key: str, device_fingerprint: str, device_name: str) -> License:
        result = self._post(
            "/api/license/activate",
            {
                "license_key": license_key,
                "device_fingerprint": device_fingerprint,
                "device_name": device_name,
                "app_version": APP_VERSION,
            },
        )
        status_code = result["status_code"]
        detail = result["body"].get("detail", "")
        if status_code == 404:
            raise LookupError(detail or "License Key 不存在，請確認輸入是否正確。")
        if status_code == 409:
            raise DeviceLimitReachedError(detail or "這組 License 的裝置數已達上限。")
        if status_code == 403:
            raise LicenseError(detail or "這組 License 無法使用，請聯絡 HouseFlow。")
        if status_code >= 400:
            raise LicenseError(detail or "啟用失敗。")

        self._cache_server_response(result["body"])
        return self._state_to_license(self._load_state())

    def get_current_license(self) -> License | None:
        state = self._load_state()
        return self._state_to_license(state) if state else None

    def check_license(self, device_fingerprint: str) -> LicenseCheckResult:
        state = self._load_state()
        license_ = self._state_to_license(state) if state else None
        now = self._now()

        if license_ is None or not license_.license_id:
            return LicenseCheckResult.blocked(LicenseStatus.EXPIRED, "尚未開始試用，也還沒有有效的 License。")

        try:
            result = self._post(
                "/api/license/verify",
                {"license_id": license_.license_id, "device_fingerprint": device_fingerprint, "app_version": APP_VERSION},
            )
        except LicenseError:
            # _post 只在 5xx 或連線失敗時才會拋 LicenseError；兩者都
            # 代表「這次連不上／server 出狀況」，退回離線寬限期判斷。
            return self._offline_fallback(license_, now)

        status_code = result["status_code"]
        body = result["body"]

        if status_code == 403:
            # Device 沒綁定 / 已被解除綁定：這不是「連不上」，是 server
            # 明確拒絕，必須要求重新啟用，不能用離線寬限期繞過。
            return LicenseCheckResult.blocked(
                license_.status, body.get("detail", "這台裝置未跟這組授權綁定，請重新啟用。")
            )
        if status_code >= 400:
            return self._offline_fallback(license_, now)

        self._cache_server_response(body)
        return self._result_from_server_body(body, now)

    # ------------------------------------------------------------------

    def _offline_fallback(self, license_: License, now: datetime) -> LicenseCheckResult:
        self._update_high_water_mark(now)
        return evaluate_license(
            license_,
            now=now,
            last_verified_at=self._last_verified_at(),
            high_water_mark=self._high_water_mark(),
            offline_grace_days=self.offline_grace_days,
        )

    @staticmethod
    def _result_from_server_body(body: dict, now: datetime) -> LicenseCheckResult:
        status = LicenseStatus(body["status"])
        valid = bool(body.get("valid"))
        message = body.get("message", "")
        latest_version = body.get("latest_version")
        minimum_supported_version = body.get("minimum_supported_version")

        days_remaining = None
        target = parse_iso(body.get("expires_at")) or parse_iso(body.get("trial_ends_at"))
        if target is not None:
            delta = target - now
            if delta.total_seconds() > 0:
                days_remaining = max(1, int(delta.total_seconds() // 86400) + (1 if delta.total_seconds() % 86400 else 0))
            else:
                days_remaining = 0

        if valid:
            return LicenseCheckResult.allowed(
                status, message, days_remaining=days_remaining,
                latest_version=latest_version, minimum_supported_version=minimum_supported_version,
            )
        return LicenseCheckResult.blocked(
            status, message, latest_version=latest_version, minimum_supported_version=minimum_supported_version,
        )


def _safe_json(response: httpx.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {}

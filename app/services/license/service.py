"""LicenseService 介面（2026-09-21 產品化 Phase 1）。Desktop 端（UI、
MainWindow 的啟動流程）只依賴這個介面，不直接依賴任何特定實作——這一輪
只有 MockLicenseProvider（本機、給開發與測試用），未來真正的
HouseFlow License Cloud provider 實作同一個介面就能直接替換，UI 端
完全不需要改。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.license.models import License, LicenseCheckResult


class LicenseError(Exception):
    """License 操作失敗（例如 License Key 不存在、裝置數已達上限）。"""


class DeviceLimitReachedError(LicenseError):
    """這組 License 的裝置數已達上限（見規格第 13 節：1 個 Professional
    License 綁定 1 台裝置）。Admin 解除某台裝置的綁定後才能在新裝置
    啟用。"""


class TrialAlreadyUsedError(LicenseError):
    """這個裝置的試用資格已經用過（見規格第 14 節：Trial 防濫用）。"""


class LicenseService(ABC):
    @abstractmethod
    def start_trial(self, device_fingerprint: str, device_name: str) -> License:
        """開始 7 天試用。同一個 device_fingerprint 只能成功一次，
        重複呼叫應該拋出 TrialAlreadyUsedError（不是靜默回傳舊的
        trial——呼叫端要能明確分辨「這是新開始的試用」還是「已經用過
        了」）。
        """

    @abstractmethod
    def activate_license(self, license_key: str, device_fingerprint: str, device_name: str) -> License:
        """用 License Key 啟用。裝置數已達上限時拋出
        DeviceLimitReachedError。"""

    @abstractmethod
    def get_current_license(self) -> License | None:
        """回傳這台裝置目前綁定的 License（trial 或 active 都算），
        沒有的話回傳 None。"""

    @abstractmethod
    def check_license(self, device_fingerprint: str) -> LicenseCheckResult:
        """完整算出目前的可用狀態，包含 offline grace／clock-tamper
        判斷（見 evaluation.evaluate_license()）。這個方法應該優先嘗試
        連線到 authoritative 的來源；離線時退回本機最後一次已知的
        verification 記錄做 offline grace 判斷。
        """

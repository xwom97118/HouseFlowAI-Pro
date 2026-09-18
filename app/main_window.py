from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QSize
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.pages.ai_center import AICenterPage
from app.pages.crm import CRMPage
from app.pages.dashboard import DashboardPage
from app.pages.groups import GroupsPage
from app.pages.placeholders import PlaceholderPage
from app.pages.poster import PosterPage
from app.pages.properties import PropertiesPage
from app.pages.schedule import ScheduleCenterPage
from app.pages.settings import SettingsPage
from app.pages.strategy import StrategyPage
from app.pages.sync_center import SyncCenterPage
from app.services.automation_engine import AutomationEngine
from app.services.database import Database
from app.styles import APP_QSS
from app.version import APP_NAME, APP_VERSION
from app.widgets.common import AccountStatusCard, BrandHeader, emoji_icon


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setWindowIcon(emoji_icon("🏠", 64))
        self.resize(1450, 880)
        self.setMinimumSize(1120, 720)
        self.setStyleSheet(APP_QSS)

        self.db = Database()
        self.current_key = "dashboard"
        self.previous_key = "dashboard"

        shell = QWidget()
        self.setCentralWidget(shell)

        outer = QHBoxLayout(shell)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)

        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 8, 12, 14)
        side_layout.setSpacing(6)

        self.brand_header = BrandHeader("HouseFlow", "PROFESSIONAL")
        side_layout.addWidget(self.brand_header)
        side_layout.addSpacing(4)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

        navs = [
            ("dashboard", "🏠", "Dashboard"),
            ("sync_center", "🔄", "同步中心"),
            ("properties", "🏡", "物件中心"),
            ("poster", "📤", "發文中心"),
            ("groups", "📂", "社團管理"),
            ("ai", "🤖", "AI 文案"),
            ("crm", "👥", "CRM"),
            ("strategy", "🤝", "成交策略"),
            ("schedule", "📅", "排程管理"),
            ("analytics", "📈", "分析"),
            ("settings", "⚙", "設定"),
        ]

        self.nav_buttons: dict[str, QPushButton] = {}
        nav_icon_size = QSize(20, 20)

        for key, icon, label in navs:
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setIcon(emoji_icon(icon, 22))
            button.setIconSize(nav_icon_size)
            button.setCheckable(True)
            button.clicked.connect(
                lambda _=False, current_key=key:
                self.navigate(current_key)
            )

            self.group.addButton(button)
            side_layout.addWidget(button)
            self.nav_buttons[key] = button

        side_layout.addStretch()

        self.account_card = AccountStatusCard(meta=APP_NAME, version=f"v{APP_VERSION}")
        side_layout.addWidget(self.account_card)

        outer.addWidget(sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)

        topbar = QFrame()
        topbar.setObjectName("Topbar")
        topbar.setFixedHeight(62)

        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(24, 0, 24, 0)

        self.back_button = QPushButton("← 返回")
        self.back_button.setObjectName("SecondaryButton")
        self.back_button.clicked.connect(self.go_back)

        self.page_title = QLabel("Dashboard")
        self.page_title.setObjectName("PageTitle")

        topbar_layout.addWidget(self.back_button)
        topbar_layout.addWidget(self.page_title)
        topbar_layout.addStretch()

        right.addWidget(topbar)

        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)

        outer.addLayout(right, 1)

        self.ai_page = AICenterPage(self.db)

        self.pages = {
            "dashboard": DashboardPage(
                self.db,
                self.navigate,
            ),
            "sync_center": SyncCenterPage(
                self.db,
                lambda: self.navigate("dashboard"),
                on_synced=self._on_dashboard_relevant_change,
            ),
            "properties": PropertiesPage(
                self.db,
                self.open_ai_for_property,
                lambda: self.navigate("dashboard"),
            ),
            "poster": PosterPage(
                self.db,
                self.navigate,
            ),
            "groups": GroupsPage(
                self.db,
                lambda: self.navigate("dashboard"),
            ),
            "ai": self.ai_page,
            "crm": CRMPage(self.db),
            "strategy": StrategyPage(self.db),
            "schedule": ScheduleCenterPage(
                self.db,
                lambda: self.navigate("dashboard"),
                on_published=self._on_dashboard_relevant_change,
            ),
            "analytics": PlaceholderPage(
                "成效分析",
                "查看物件與Facebook發布紀錄。",
            ),
            "settings": SettingsPage(self.db, on_saved=self._on_settings_saved),
        }

        for page in self.pages.values():
            self.stack.addWidget(page)

        self._refresh_sidebar_footer()

        self.navigate(
            "dashboard",
            remember=False,
        )

        self._quit_requested = False
        self._tray_notice_shown = False

        self.engine = AutomationEngine(self.db)
        self.engine.status_changed.connect(self._on_automation_status_changed)
        self.engine.notify.connect(self._on_automation_notify)
        self.engine.cycle_finished.connect(self._on_automation_cycle_finished)
        self.engine.login_required.connect(self._on_automation_login_required)
        self.account_card.automation_toggle_btn.clicked.connect(self._toggle_automation)

        self._build_tray_icon()
        self.engine.start()
        self.engine.trigger_now()  # 開機立即跑一次：復原卡住的排程、補上睡眠/關機期間錯過的到期工作
        self._sync_automation_toggle_label()

    # ------------------------------------------------------------------
    # 系統匣 + Automation Engine
    # ------------------------------------------------------------------

    def _build_tray_icon(self) -> None:
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.windowIcon())
        self.tray_icon.setToolTip(f"{APP_NAME} {APP_VERSION}")

        menu = QMenu()
        open_action = menu.addAction("開啟HouseFlow")
        open_action.triggered.connect(self._show_from_tray)

        self.tray_pause_action = menu.addAction("暫停自動化")
        self.tray_pause_action.triggered.connect(self.engine.pause)
        self.tray_resume_action = menu.addAction("繼續自動化")
        self.tray_resume_action.triggered.connect(self.engine.resume)

        check_now_action = menu.addAction("立即檢查排程")
        check_now_action.triggered.connect(lambda: self.engine.trigger_now())

        menu.addSeparator()
        quit_action = menu.addAction("退出HouseFlow")
        quit_action.triggered.connect(self._quit_from_tray)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._quit_requested = True
        self.close()

    def _toggle_automation(self) -> None:
        if self.engine.is_paused():
            self.engine.resume()
        else:
            self.engine.pause()
        self._sync_automation_toggle_label()

    def _sync_automation_toggle_label(self) -> None:
        paused = self.engine.is_paused()
        self.account_card.automation_toggle_btn.setText("繼續自動化" if paused else "暫停自動化")
        if hasattr(self, "tray_pause_action"):
            self.tray_pause_action.setVisible(not paused)
            self.tray_resume_action.setVisible(paused)

    def _on_automation_status_changed(self, text: str, kind: str) -> None:
        self.account_card.set_automation_status(text, kind)
        self._sync_automation_toggle_label()

    def _on_automation_notify(self, message: str) -> None:
        if hasattr(self, "tray_icon"):
            self.tray_icon.showMessage(
                APP_NAME, message, QSystemTrayIcon.MessageIcon.Information, 5000
            )

    def _on_automation_cycle_finished(self) -> None:
        schedule_page = self.pages.get("schedule")
        if schedule_page is not None and hasattr(schedule_page, "refresh"):
            schedule_page.refresh()
        self._on_dashboard_relevant_change()

    def _on_automation_login_required(self) -> None:
        # 視窗已經被最小化到系統匣時不跳出遮住畫面的對話框——tray 通知
        # （engine.notify）跟側邊欄狀態已經足以提醒，使用者打開視窗時
        # 才需要這個比較顯眼的提醒。
        if not self.isVisible():
            return
        QMessageBox.warning(
            self,
            "Facebook 需要重新登入",
            "自動排程發布／刪文暫停中，請到「發文中心」重新登入 Facebook，"
            "登入完成後自動化會自動恢復。",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        minimize_to_tray = self.db.get_setting("minimize_to_tray", "1") == "1"

        if not self._quit_requested and minimize_to_tray and hasattr(self, "tray_icon"):
            event.ignore()
            self.hide()
            if not self._tray_notice_shown:
                self._tray_notice_shown = True
                self.tray_icon.showMessage(
                    APP_NAME,
                    "HouseFlow 已在背景執行，自動排程仍會繼續。",
                    QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
            return

        if hasattr(self, "engine"):
            self.engine.stop()
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        event.accept()

        # setQuitOnLastWindowClosed(False)（見 app/application.py）讓
        # 「隱藏視窗最小化到系統匣」不會誤觸發整個 app 結束；真的要退出
        # （這裡、或使用者按了 X 但設定沒開最小化到系統匣）時，
        # 必須自己呼叫 quit() 讓事件迴圈真的結束。
        app = QCoreApplication.instance()
        if app is not None:
            app.quit()

    def navigate(
        self,
        key: str,
        remember: bool = True,
    ) -> None:
        if key not in self.pages:
            return

        if (
            key == "ai"
            and self.db.get_setting(
                "ai_enabled",
                "0",
            ) != "1"
        ):
            QMessageBox.information(
                self,
                "AI 目前已關閉",
                "目前先停用 OpenAI，"
                "可在設定頁重新開啟。",
            )
            return

        if remember and key != self.current_key:
            self.previous_key = self.current_key

        self.current_key = key
        page = self.pages[key]

        self._refresh_sidebar_footer()
        self.stack.setCurrentWidget(page)
        self.nav_buttons[key].setChecked(True)

        titles = {
            "dashboard": "Dashboard",
            "sync_center": "同步中心",
            "properties": "物件中心",
            "poster": "Facebook 發文中心",
            "groups": "Facebook 社團管理",
            "ai": "AI 文案中心",
            "crm": "CRM",
            "strategy": "成交策略",
            "schedule": "排程管理",
            "analytics": "成效分析",
            "settings": "設定",
        }

        self.page_title.setText(titles[key])
        self.back_button.setVisible(
            key != "dashboard"
        )

        if hasattr(page, "refresh"):
            page.refresh()

        if hasattr(page, "reload_properties"):
            page.reload_properties()

        if hasattr(page, "reload_groups"):
            page.reload_groups()

    def go_back(self) -> None:
        target = (
            self.previous_key
            if self.previous_key in self.pages
            else "dashboard"
        )

        if target == self.current_key:
            target = "dashboard"

        self.navigate(
            target,
            remember=False,
        )

    def open_ai_for_property(
        self,
        property_id: int,
    ) -> None:
        if self.db.get_setting(
            "ai_enabled",
            "0",
        ) != "1":
            QMessageBox.information(
                self,
                "AI 目前已關閉",
                "請先到設定頁開啟 AI 功能。",
            )
            return

        self.ai_page.select_property(property_id)
        self.navigate("ai")

    def _refresh_sidebar_footer(self) -> None:
        display_name = self.db.get_setting("display_name", "").strip()
        self.account_card.set_name(display_name)

    def _on_settings_saved(self) -> None:
        if hasattr(self, "engine"):
            self.engine.sync_from_settings()
            self._sync_automation_toggle_label()

    def _on_dashboard_relevant_change(self) -> None:
        properties_page = self.pages.get("properties")
        if properties_page is not None and hasattr(properties_page, "refresh"):
            properties_page.refresh()
        dashboard_page = self.pages.get("dashboard")
        if dashboard_page is not None and hasattr(dashboard_page, "refresh"):
            dashboard_page.refresh()
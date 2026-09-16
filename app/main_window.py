from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
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
from app.pages.settings import SettingsPage
from app.pages.strategy import StrategyPage
from app.pages.sync_center import SyncCenterPage
from app.services.database import Database
from app.styles import APP_QSS


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("HouseFlow Professional 3.0.0")
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

        brand = QLabel("HouseFlow AI")
        brand.setObjectName("Brand")
        side_layout.addWidget(brand)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

        navs = [
            ("dashboard", "🏠  Dashboard"),
            ("sync_center", "🔄  同步中心"),
            ("properties", "🏡  物件中心"),
            ("poster", "📤  發文中心"),
            ("groups", "📂  社團管理"),
            ("ai", "🤖  AI 文案"),
            ("crm", "👥  CRM"),
            ("strategy", "🤝  成交策略"),
            ("schedule", "📅  排程"),
            ("analytics", "📈  分析"),
            ("settings", "⚙  設定"),
        ]

        self.nav_buttons: dict[str, QPushButton] = {}

        for key, text in navs:
            button = QPushButton(text)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda _=False, current_key=key:
                self.navigate(current_key)
            )

            self.group.addButton(button)
            side_layout.addWidget(button)
            self.nav_buttons[key] = button

        side_layout.addStretch()

        user = QLabel("黃冠嘉\n龍潭成交策略")
        user.setStyleSheet(
            "color:#94A3B8;padding:12px;"
        )
        side_layout.addWidget(user)

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
        topbar_layout.addWidget(QLabel("Professional 2.0"))

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
                on_synced=self._on_properties_synced,
            ),
            "properties": PropertiesPage(
                self.db,
                self.open_ai_for_property,
                lambda: self.navigate("dashboard"),
            ),
            "poster": PosterPage(
                self.db,
                lambda: self.navigate("dashboard"),
            ),
            "groups": GroupsPage(
                self.db,
                lambda: self.navigate("dashboard"),
            ),
            "ai": self.ai_page,
            "crm": CRMPage(self.db),
            "strategy": StrategyPage(self.db),
            "schedule": PlaceholderPage(
                "排程中心",
                "以30分鐘為單位管理Facebook發布時間。",
            ),
            "analytics": PlaceholderPage(
                "成效分析",
                "查看物件與Facebook發布紀錄。",
            ),
            "settings": SettingsPage(self.db),
        }

        for page in self.pages.values():
            self.stack.addWidget(page)

        self.navigate(
            "dashboard",
            remember=False,
        )

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
            "schedule": "排程中心",
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

    def _on_properties_synced(self) -> None:
        properties_page = self.pages.get("properties")
        if properties_page is not None and hasattr(properties_page, "refresh"):
            properties_page.refresh()
        dashboard_page = self.pages.get("dashboard")
        if dashboard_page is not None and hasattr(dashboard_page, "refresh"):
            dashboard_page.refresh()
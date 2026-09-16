from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.database import Database


class DashboardMetricCard(QFrame):
    def __init__(
        self,
        icon: str,
        title: str,
        subtitle: str,
    ) -> None:
        super().__init__()

        self.setObjectName("DashboardMetricCard")
        self.setMinimumHeight(138)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(8)

        header = QHBoxLayout()

        icon_label = QLabel(icon)
        icon_label.setObjectName("MetricIcon")
        icon_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        title_label = QLabel(title)
        title_label.setObjectName("MetricTitle")

        header.addWidget(icon_label)
        header.addWidget(title_label)
        header.addStretch()

        self.value_label = QLabel("0")
        self.value_label.setObjectName("DashboardMetricValue")

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("MetricSubtitle")

        root.addLayout(header)
        root.addWidget(self.value_label)
        root.addWidget(subtitle_label)

    def set_value(self, value: int | str) -> None:
        self.value_label.setText(str(value))


class QuickActionButton(QPushButton):
    def __init__(
        self,
        icon: str,
        title: str,
        subtitle: str,
    ) -> None:
        super().__init__()

        self.setObjectName("QuickActionButton")
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.setMinimumHeight(76)
        self.setText(
            f"{icon}  {title}\n"
            f"     {subtitle}"
        )


class DashboardPage(QWidget):
    def __init__(
        self,
        db: Database,
        navigate,
    ) -> None:
        super().__init__()

        self.db = db
        self.navigate = navigate

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(20)

        hero = QFrame()
        hero.setObjectName("DashboardHero")

        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(
            24,
            22,
            24,
            22,
        )

        hero_text = QVBoxLayout()
        hero_text.setSpacing(4)

        self.greeting_label = QLabel("歡迎回來 👋")
        self.greeting_label.setObjectName(
            "DashboardGreeting"
        )

        self.hero_subtitle = QLabel(
            "今天也一起把重要的工作完成。"
        )
        self.hero_subtitle.setObjectName(
            "DashboardSubtitle"
        )

        hero_text.addWidget(
            self.greeting_label
        )
        hero_text.addWidget(
            self.hero_subtitle
        )

        self.sync_button = QPushButton(
            "＋ 同步最新物件"
        )
        self.sync_button.setObjectName(
            "HeroPrimaryButton"
        )
        self.sync_button.clicked.connect(
            lambda: self.navigate("properties")
        )

        hero_layout.addLayout(hero_text, 1)
        hero_layout.addWidget(self.sync_button)

        root.addWidget(hero)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(14)
        metrics.setVerticalSpacing(14)

        self.cards = {
            "properties": DashboardMetricCard(
                "🏠",
                "全部物件",
                "目前已同步物件",
            ),
            "favorites": DashboardMetricCard(
                "★",
                "收藏物件",
                "重點追蹤清單",
            ),
            "drafts": DashboardMetricCard(
                "📝",
                "文案紀錄",
                "已儲存文案",
            ),
            "contacts": DashboardMetricCard(
                "👥",
                "CRM 客戶",
                "買方與屋主",
            ),
        }

        for index, card in enumerate(
            self.cards.values()
        ):
            metrics.addWidget(
                card,
                0,
                index,
            )
            metrics.setColumnStretch(
                index,
                1,
            )

        root.addLayout(metrics)

        content = QHBoxLayout()
        content.setSpacing(16)

        quick_card = QFrame()
        quick_card.setObjectName("DashboardPanel")

        quick_layout = QVBoxLayout(quick_card)
        quick_layout.setContentsMargins(
            22,
            20,
            22,
            22,
        )
        quick_layout.setSpacing(12)

        quick_title = QLabel("快速操作")
        quick_title.setObjectName("PanelTitle")

        quick_subtitle = QLabel(
            "從常用功能快速開始今天的工作"
        )
        quick_subtitle.setObjectName(
            "PanelSubtitle"
        )

        quick_layout.addWidget(quick_title)
        quick_layout.addWidget(quick_subtitle)

        quick_actions = [
            (
                "🏡",
                "同步／管理物件",
                "更新物件資料與照片",
                "properties",
            ),
            (
                "📤",
                "Facebook 發文",
                "準備個人與多社團貼文",
                "poster",
            ),
            (
                "📂",
                "管理社團",
                "新增、停用與整理社團",
                "groups",
            ),
            (
                "⚙",
                "個人化設定",
                "調整品牌與文案資料",
                "settings",
            ),
        ]

        for icon, title, subtitle, page in quick_actions:
            button = QuickActionButton(
                icon,
                title,
                subtitle,
            )
            button.clicked.connect(
                lambda _=False, key=page:
                self.navigate(key)
            )
            quick_layout.addWidget(button)

        quick_layout.addStretch()

        work_card = QFrame()
        work_card.setObjectName("DashboardPanel")

        work_layout = QVBoxLayout(work_card)
        work_layout.setContentsMargins(
            22,
            20,
            22,
            22,
        )
        work_layout.setSpacing(14)

        work_header = QHBoxLayout()

        work_title_box = QVBoxLayout()
        work_title_box.setSpacing(3)

        work_title = QLabel("今日工作建議")
        work_title.setObjectName("PanelTitle")

        work_subtitle = QLabel(
            "依照目前資料，建議先完成以下工作"
        )
        work_subtitle.setObjectName(
            "PanelSubtitle"
        )

        work_title_box.addWidget(work_title)
        work_title_box.addWidget(work_subtitle)

        work_header.addLayout(work_title_box)
        work_header.addStretch()

        work_layout.addLayout(work_header)

        self.tasks_container = QVBoxLayout()
        self.tasks_container.setSpacing(10)
        work_layout.addLayout(self.tasks_container)

        work_layout.addStretch()

        tip = QFrame()
        tip.setObjectName("DashboardTip")

        tip_layout = QVBoxLayout(tip)
        tip_layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )
        tip_layout.setSpacing(5)

        tip_title = QLabel("今日小提醒")
        tip_title.setObjectName("TipTitle")

        self.tip_label = QLabel(
            "先完成同步，再挑選主推物件準備貼文，"
            "可以讓今天的社群工作更有效率。"
        )
        self.tip_label.setObjectName("TipText")
        self.tip_label.setWordWrap(True)

        tip_layout.addWidget(tip_title)
        tip_layout.addWidget(self.tip_label)

        work_layout.addWidget(tip)

        content.addWidget(quick_card, 5)
        content.addWidget(work_card, 7)

        root.addLayout(content, 1)

        self.refresh()

    def _clear_tasks(self) -> None:
        while self.tasks_container.count():
            item = self.tasks_container.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

    def _add_task(
        self,
        icon: str,
        title: str,
        subtitle: str,
        button_text: str,
        page: str,
    ) -> None:
        row = QFrame()
        row.setObjectName("TaskRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(
            16,
            13,
            14,
            13,
        )
        layout.setSpacing(12)

        icon_label = QLabel(icon)
        icon_label.setObjectName("TaskIcon")
        icon_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        text_box = QVBoxLayout()
        text_box.setSpacing(2)

        title_label = QLabel(title)
        title_label.setObjectName("TaskTitle")

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName(
            "TaskSubtitle"
        )

        text_box.addWidget(title_label)
        text_box.addWidget(subtitle_label)

        action = QPushButton(button_text)
        action.setObjectName("TaskButton")
        action.clicked.connect(
            lambda: self.navigate(page)
        )

        layout.addWidget(icon_label)
        layout.addLayout(text_box, 1)
        layout.addWidget(action)

        self.tasks_container.addWidget(row)

    def refresh(self) -> None:
        counts = self.db.dashboard_counts()

        for key, card in self.cards.items():
            card.set_value(
                counts.get(key, 0)
            )

        display_name = self.db.get_setting(
            "display_name",
            "",
        ).strip()

        agent_name = self.db.get_setting(
            "agent_name",
            "",
        ).strip()

        name = display_name or agent_name or "使用者"

        self.greeting_label.setText(
            f"歡迎回來，{name} 👋"
        )

        properties = int(
            counts.get("properties", 0)
        )
        favorites = int(
            counts.get("favorites", 0)
        )
        drafts = int(
            counts.get("drafts", 0)
        )
        contacts = int(
            counts.get("contacts", 0)
        )

        self.hero_subtitle.setText(
            f"目前共有 {properties} 筆物件，"
            "今天也一起把重要的工作完成。"
        )

        self._clear_tasks()

        if properties == 0:
            self._add_task(
                "🏡",
                "同步第一批物件",
                "從永慶／台慶店頭頁面匯入物件",
                "開始同步",
                "properties",
            )
        else:
            self._add_task(
                "🔄",
                "確認最新物件",
                f"目前資料庫共有 {properties} 筆物件",
                "前往物件",
                "properties",
            )

        if favorites == 0:
            self._add_task(
                "★",
                "挑選今日主推物件",
                "收藏準備曝光或優先追蹤的物件",
                "選擇物件",
                "properties",
            )
        else:
            self._add_task(
                "★",
                "查看收藏物件",
                f"目前有 {favorites} 筆重點物件",
                "查看收藏",
                "properties",
            )

        self._add_task(
            "📤",
            "準備今日 Facebook 貼文",
            "確認文案、圖片與發布社團",
            "開始發文",
            "poster",
        )

        if contacts == 0:
            self._add_task(
                "👥",
                "建立第一筆客戶資料",
                "開始整理買方與屋主名單",
                "新增客戶",
                "crm",
            )
        else:
            self._add_task(
                "👥",
                "追蹤客戶進度",
                f"目前共有 {contacts} 位客戶",
                "查看 CRM",
                "crm",
            )

        if drafts == 0:
            self.tip_label.setText(
                "今天可以先完成物件同步，挑選一間主推物件，"
                "再到發文中心確認文案與照片。"
            )
        else:
            self.tip_label.setText(
                f"目前已儲存 {drafts} 筆文案紀錄。"
                "發文前記得再次確認價格、照片順序與 CTA。"
            )
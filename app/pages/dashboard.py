from __future__ import annotations

from typing import Callable

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
        on_start_review: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()

        self.db = db
        self.navigate = navigate
        self.on_start_review = on_start_review

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

        today_card = QFrame()
        today_card.setObjectName("DashboardPanel")
        today_layout = QHBoxLayout(today_card)
        today_layout.setContentsMargins(22, 18, 22, 18)
        today_layout.setSpacing(18)

        today_text = QVBoxLayout()
        today_text.setSpacing(4)
        today_title = QLabel("📤 今日發文")
        today_title.setObjectName("PanelTitle")
        self.today_summary_label = QLabel("今天共 0 篇")
        self.today_summary_label.setObjectName("PanelSubtitle")
        self.today_detail_label = QLabel("待檢核 0　待發布 0　已發布 0　失敗 0")
        self.today_detail_label.setObjectName("Muted")
        today_text.addWidget(today_title)
        today_text.addWidget(self.today_summary_label)
        today_text.addWidget(self.today_detail_label)

        today_layout.addLayout(today_text, 1)

        self.start_review_button = QPushButton("開始今日檢核")
        self.start_review_button.setObjectName("PrimaryButton")
        self.start_review_button.clicked.connect(self._start_review)
        today_layout.addWidget(self.start_review_button)

        root.addWidget(today_card)

        sync_card = QFrame()
        sync_card.setObjectName("DashboardPanel")
        sync_layout = QHBoxLayout(sync_card)
        sync_layout.setContentsMargins(22, 18, 22, 18)
        sync_layout.setSpacing(18)

        sync_text = QVBoxLayout()
        sync_text.setSpacing(4)
        sync_title = QLabel("🔄 同步狀態")
        sync_title.setObjectName("PanelTitle")
        self.sync_status_label = QLabel("自動同步：● 運行中")
        self.sync_status_label.setObjectName("PanelSubtitle")
        self.sync_detail_label = QLabel("來源 0　下次同步 —　今日新增 0　今日異動 0")
        self.sync_detail_label.setObjectName("Muted")
        self.sync_warning_label = QLabel("")
        self.sync_warning_label.setObjectName("WarningText")
        self.sync_warning_label.setVisible(False)
        sync_text.addWidget(sync_title)
        sync_text.addWidget(self.sync_status_label)
        sync_text.addWidget(self.sync_detail_label)
        sync_text.addWidget(self.sync_warning_label)

        sync_layout.addLayout(sync_text, 1)

        self.view_sync_center_button = QPushButton("查看同步中心")
        self.view_sync_center_button.setObjectName("SecondaryButton")
        self.view_sync_center_button.clicked.connect(lambda: self.navigate("sync_center"))
        sync_layout.addWidget(self.view_sync_center_button)

        root.addWidget(sync_card)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(14)
        metrics.setVerticalSpacing(14)

        # 2026-09-22 產品化 Phase 1.1：CRM 已經從 V1 導覽隱藏（見
        # main_window.py 的 V1_HIDDEN_NAV_KEYS），Dashboard 不應該再顯示
        # 一張使用者點不到入口的「CRM 客戶」卡片。這裡沿用跟導覽列同樣
        # 的「過濾清單」寫法，之後要重新開放 CRM 時，把 "contacts" 從
        # V1_HIDDEN_METRIC_KEYS 移除即可，不需要改動其他邏輯——
        # self.cards.items() 的 refresh 迴圈本來就是通用的，不會因為
        # 少了 "contacts" 這個 key 而出錯。
        V1_HIDDEN_METRIC_KEYS = {"contacts"}

        all_cards = {
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
        self.cards = {
            key: card
            for key, card in all_cards.items()
            if key not in V1_HIDDEN_METRIC_KEYS
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

    def _start_review(self) -> None:
        if callable(self.on_start_review):
            self.on_start_review()
        else:
            self.navigate("schedule")

    def refresh(self) -> None:
        counts = self.db.dashboard_counts()

        today = self.db.today_automation_summary()
        pending = int(today.get("pending_review_today", 0))
        scheduled = int(today.get("scheduled_today", 0))
        published = int(today.get("published_today", 0))
        failed = int(today.get("failed_today", 0))
        total_today = pending + scheduled + published + failed
        self.today_summary_label.setText(f"今天共 {total_today} 篇")
        self.today_detail_label.setText(
            f"待檢核 {pending}　待發布 {scheduled}　已發布 {published}　失敗 {failed}"
        )

        sync_summary = self.db.sync_dashboard_summary()
        automation_on = self.db.get_setting("automation_enabled", "1") == "1"
        sync_on = self.db.get_setting("automation_sync_enabled", "1") == "1"
        if automation_on and sync_on:
            self.sync_status_label.setText("自動同步：● 運行中")
        else:
            self.sync_status_label.setText("自動同步：○ 已關閉")

        next_sync = sync_summary.get("next_sync_at") or "—"
        self.sync_detail_label.setText(
            f"來源 {sync_summary.get('auto_sync_sources', 0)}　"
            f"下次同步 {next_sync}　"
            f"今日新增 {sync_summary.get('today_new', 0)}　"
            f"今日異動 {sync_summary.get('today_changed', 0)}"
        )

        failing = int(sync_summary.get("failing_sources", 0))
        if failing:
            self.sync_warning_label.setText(f"⚠ {failing} 個來源同步失敗")
            self.sync_warning_label.setVisible(True)
        else:
            self.sync_warning_label.setVisible(False)

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

        # 2026-09-21 產品化 Phase 1：CRM 在 V1 從導覽隱藏，這裡對應的
        # 待辦建議（原本會導去 "crm"）一併拿掉，避免建議一個 sidebar
        # 沒有入口的頁面。contacts 變數保留給 Dashboard 其他統計使用。
        _ = contacts

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
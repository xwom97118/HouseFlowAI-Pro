from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from app.services.database import Database
from app.widgets.common import SectionTitle


class StrategyPage(QWidget):
    def __init__(self, db: Database) -> None:
        super().__init__(); self.db = db
        root = QVBoxLayout(self); root.setContentsMargins(24, 22, 24, 24); root.setSpacing(14)
        root.addWidget(SectionTitle("龍潭成交策略", "輸入案件條件，建立談判節奏、話術與內容素材。"))
        split = QSplitter(Qt.Orientation.Horizontal)
        form_box = QWidget(); form = QFormLayout(form_box)
        self.title = QLineEdit(); self.title.setPlaceholderText("例如：幸福山丘三房談判")
        self.asking = QLineEdit(); self.asking.setPlaceholderText("例如：1,680萬")
        self.offer = QLineEdit(); self.offer.setPlaceholderText("例如：1,500萬")
        self.floor = QLineEdit(); self.floor.setPlaceholderText("屋主底價（未知可留白）")
        self.situation = QTextEdit(); self.situation.setPlaceholderText("買方條件、屋主動機、貸款狀況、時間壓力…")
        for label, widget in [("案件名稱", self.title), ("屋主開價", self.asking), ("買方出價", self.offer), ("屋主底價", self.floor), ("案件情況", self.situation)]: form.addRow(label, widget)
        generate = QPushButton("產生成交策略"); generate.setObjectName("PrimaryButton"); generate.clicked.connect(self.generate)
        save = QPushButton("儲存紀錄"); save.setObjectName("SecondaryButton"); save.clicked.connect(self.save)
        buttons = QHBoxLayout(); buttons.addWidget(generate); buttons.addWidget(save); form.addRow(buttons)
        result_box = QWidget(); rl = QVBoxLayout(result_box); rl.addWidget(QLabel("策略結果"))
        self.result = QTextEdit(); self.result.setPlaceholderText("策略會顯示在這裡，可自行修改後儲存。")
        rl.addWidget(self.result)
        split.addWidget(form_box); split.addWidget(result_box); split.setSizes([480, 720])
        root.addWidget(split, 2)
        self.history = QTableWidget(0, 5); self.history.setHorizontalHeaderLabels(["日期", "案件", "開價", "出價", "策略摘要"])
        self.history.horizontalHeader().setStretchLastSection(True); root.addWidget(self.history, 1)
        self.refresh()

    def generate(self) -> None:
        title = self.title.text().strip() or "本案"
        ask = self.asking.text().strip() or "未提供"
        offer = self.offer.text().strip() or "未提供"
        floor = self.floor.text().strip() or "尚未確認"
        situation = self.situation.toPlainText().strip() or "未提供其他背景"
        text = f"""【{title}】成交策略\n\n一、先確認三個關鍵\n1. 屋主真正底價：{floor}\n2. 買方可承受上限：目前出價 {offer}\n3. 雙方時間壓力與成交動機：{situation}\n\n二、談判節奏\n• 第一輪不急著只談價差，先讓屋主理解買方的付款能力、貸款條件與簽約誠意。\n• 將開價 {ask} 與出價 {offer} 的差距拆成條件交換，例如交屋期、付款節點、服務費與屋況處理。\n• 每次讓價都要換取明確承諾，不做沒有條件的單方面退讓。\n• 若雙方接近，安排限時書面斡旋或當面協商，避免口頭反覆。\n\n三、對屋主話術\n「現在不是要您立刻接受這個數字，而是先確認：在付款安全、簽約速度與交屋條件都能配合的前提下，您願意往哪個區間談？我才能把買方往上推。」\n\n四、對買方話術\n「我會替你守住價格，但屋主願意談的前提，是你能提出明確的成交條件。請先確認最高可接受總價與今天能否簽約，我才有籌碼去談。」\n\n五、成交底線\n• 未確認貸款與資金前，不承諾成交。\n• 未換到屋主書面回覆前，不讓買方無限加價。\n• 價格、服務費、交屋日、附贈物與現況交屋一次寫清楚。\n"""
        self.result.setPlainText(text)

    def save(self) -> None:
        if not self.result.toPlainText().strip(): self.generate()
        self.db.save_strategy({"title": self.title.text(), "asking_price": self.asking.text(), "buyer_offer": self.offer.text(), "owner_floor": self.floor.text(), "situation": self.situation.toPlainText(), "strategy": self.result.toPlainText()})
        self.refresh(); QMessageBox.information(self, "已儲存", "成交策略已存入歷史紀錄。")

    def refresh(self) -> None:
        rows = self.db.list_strategies(); self.history.setRowCount(len(rows))
        for i, row in enumerate(rows):
            vals = [row.get("created_at", ""), row.get("title", ""), row.get("asking_price", ""), row.get("buyer_offer", ""), str(row.get("strategy", ""))[:100]]
            for j, value in enumerate(vals): self.history.setItem(i, j, QTableWidgetItem(str(value or "")))
        self.history.resizeColumnsToContents(); self.history.setColumnWidth(4, 480)

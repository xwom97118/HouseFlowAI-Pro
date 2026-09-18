from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PropertyPicker(QWidget):
    """
    下拉式物件選擇器。

    上方提供搜尋、行政區、類型、總價及排序條件；
    下方的物件下拉選單會顯示所有篩選後的物件。
    """

    property_selected = Signal(int)

    def __init__(self) -> None:
        super().__init__()

        self._rows: list[dict[str, Any]] = []
        self._filtered_rows: list[dict[str, Any]] = []
        self._selected_id: int | None = None

        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(250)
        self._search_debounce.timeout.connect(self.apply_filters)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "搜尋標題、地址、價格、格局、標籤……"
        )
        self.search.textChanged.connect(
            self._search_debounce.start
        )

        self.region = QComboBox()
        self.region.addItem("全部行政區", "")

        self.property_type = QComboBox()
        self.property_type.addItems(
            [
                "全部類型",
                "住宅",
                "大樓",
                "華廈",
                "公寓",
                "透天",
                "別墅",
                "套房",
                "店面",
                "土地",
                "廠房",
            ]
        )

        self.price_range = QComboBox()
        self.price_range.addItems(
            [
                "全部總價",
                "500萬以下",
                "500～1000萬",
                "1000～1500萬",
                "1500～2000萬",
                "2000～3000萬",
                "3000萬以上",
            ]
        )

        self.sort_by = QComboBox()
        self.sort_by.addItems(
            [
                "最新同步",
                "總價低至高",
                "總價高至低",
                "坪數大至小",
                "坪數小至大",
                "收藏優先",
                "名稱排序",
            ]
        )

        self.reset_button = QPushButton("重設篩選")
        self.reset_button.setObjectName("SecondaryButton")
        self.reset_button.clicked.connect(
            self.reset_filters
        )

        for widget in (
            self.region,
            self.property_type,
            self.price_range,
            self.sort_by,
        ):
            widget.currentIndexChanged.connect(
                self.apply_filters
            )

        filter_row.addWidget(self.search, 3)
        filter_row.addWidget(self.region, 1)
        filter_row.addWidget(self.property_type, 1)
        filter_row.addWidget(self.price_range, 1)
        filter_row.addWidget(self.sort_by, 1)
        filter_row.addWidget(self.reset_button)

        root.addLayout(filter_row)

        result_row = QHBoxLayout()
        result_row.setSpacing(8)

        self.result_label = QLabel("共 0 筆")
        self.result_label.setObjectName("MutedLabel")

        self.property_combo = QComboBox()
        self.property_combo.setMinimumHeight(42)
        self.property_combo.setMaxVisibleItems(25)
        self.property_combo.currentIndexChanged.connect(
            self._combo_changed
        )

        result_row.addWidget(self.result_label)
        result_row.addWidget(self.property_combo, 1)

        root.addLayout(result_row)

    def set_properties(
        self,
        rows: list[dict[str, Any]],
        selected_id: int | None = None,
    ) -> None:
        self._rows = [
            dict(row)
            for row in rows
        ]

        if selected_id is not None:
            self._selected_id = int(selected_id)

        current_region = self.region.currentData()

        regions = sorted(
            {
                self._extract_region(
                    str(row.get("address") or "")
                )
                for row in self._rows
            }
            - {""}
        )

        self.region.blockSignals(True)
        self.region.clear()
        self.region.addItem(
            "全部行政區",
            "",
        )

        for region in regions:
            self.region.addItem(
                region,
                region,
            )

        region_index = self.region.findData(
            current_region
        )
        self.region.setCurrentIndex(
            region_index
            if region_index >= 0
            else 0
        )
        self.region.blockSignals(False)

        self.apply_filters()

    def current_property_id(
        self,
    ) -> int | None:
        value = self.property_combo.currentData()

        if value is not None:
            return int(value)

        return self._selected_id

    def select_property(
        self,
        property_id: int,
    ) -> None:
        # 不能先設 self._selected_id 再呼叫 setCurrentIndex()——
        # _combo_changed() 會用「新 id 跟 self._selected_id 是否相同」
        # 判斷要不要真的 emit property_selected，先設就會被自己的防重複
        # 邏輯擋掉，呼叫端永遠收不到通知。讓 _combo_changed() 自然處理。
        target_id = int(property_id)
        index = self.property_combo.findData(target_id)

        if index >= 0:
            self.property_combo.setCurrentIndex(index)
        else:
            self._selected_id = target_id

    def reset_filters(self) -> None:
        self.search.blockSignals(True)
        self.region.blockSignals(True)
        self.property_type.blockSignals(True)
        self.price_range.blockSignals(True)
        self.sort_by.blockSignals(True)

        self.search.clear()
        self.region.setCurrentIndex(0)
        self.property_type.setCurrentIndex(0)
        self.price_range.setCurrentIndex(0)
        self.sort_by.setCurrentIndex(0)

        self.search.blockSignals(False)
        self.region.blockSignals(False)
        self.property_type.blockSignals(False)
        self.price_range.blockSignals(False)
        self.sort_by.blockSignals(False)

        self.apply_filters()

    def apply_filters(self) -> None:
        previous_id = self.current_property_id()

        query = self.search.text().strip().lower()
        selected_region = str(
            self.region.currentData()
            or ""
        )
        selected_type = (
            self.property_type.currentText()
        )
        selected_price = (
            self.price_range.currentText()
        )
        selected_sort = (
            self.sort_by.currentText()
        )

        filtered: list[dict[str, Any]] = []

        for row in self._rows:
            title = str(row.get("title") or "")
            address = str(row.get("address") or "")
            price = str(row.get("price") or "")
            layout = str(row.get("layout") or "")
            size = str(row.get("size") or "")
            tag = str(row.get("tag") or "")
            external_id = str(
                row.get("external_id")
                or ""
            )

            searchable = " ".join(
                [
                    title,
                    address,
                    price,
                    layout,
                    size,
                    tag,
                    external_id,
                ]
            ).lower()

            if query and query not in searchable:
                continue

            if (
                selected_region
                and selected_region not in address
            ):
                continue

            detected_type = self._detect_type(
                row
            )

            if (
                selected_type != "全部類型"
                and selected_type != detected_type
            ):
                continue

            price_number = self._parse_number(
                price
            )

            if not self._price_matches(
                selected_price,
                price_number,
            ):
                continue

            filtered.append(row)

        self._filtered_rows = self._sort_rows(
            filtered,
            selected_sort,
        )

        self._reload_property_combo(
            previous_id
        )

    def _reload_property_combo(
        self,
        previous_id: int | None,
    ) -> None:
        self.property_combo.blockSignals(True)
        self.property_combo.clear()

        for row in self._filtered_rows:
            property_id = int(
                row.get("id")
                or 0
            )
            title = str(
                row.get("title")
                or f"物件 #{property_id}"
            )
            price = str(
                row.get("price")
                or "價格洽詢"
            )
            address = str(
                row.get("address")
                or ""
            )
            layout = str(
                row.get("layout")
                or ""
            )
            size = str(
                row.get("size")
                or ""
            )
            favorite = (
                "★ "
                if row.get("favorite")
                else ""
            )

            details = "｜".join(
                value
                for value in (
                    layout,
                    size,
                )
                if value
            )

            display_parts = [
                f"{favorite}{title}",
                price,
            ]

            if details:
                display_parts.append(details)

            if address:
                display_parts.append(address)

            display = "　｜　".join(
                display_parts
            )

            self.property_combo.addItem(
                display,
                property_id,
            )

        self.result_label.setText(
            f"共 {len(self._filtered_rows)} 筆"
        )

        if not self._filtered_rows:
            self.property_combo.addItem(
                "沒有符合條件的物件",
                None,
            )
            self.property_combo.setEnabled(
                False
            )
            self._selected_id = None

        else:
            self.property_combo.setEnabled(
                True
            )

            target_id = (
                previous_id
                if previous_id is not None
                else self._selected_id
            )

            target_index = (
                self.property_combo.findData(
                    target_id
                )
                if target_id is not None
                else -1
            )

            if target_index < 0:
                target_index = 0

            self.property_combo.setCurrentIndex(
                target_index
            )

            selected = (
                self.property_combo.currentData()
            )

            self._selected_id = (
                int(selected)
                if selected is not None
                else None
            )

        self.property_combo.blockSignals(False)

        if self._selected_id is not None:
            self.property_selected.emit(
                self._selected_id
            )

    def _combo_changed(
        self,
        index: int,
    ) -> None:
        if index < 0:
            return

        value = self.property_combo.itemData(
            index
        )

        if value is None:
            return

        property_id = int(value)

        if property_id == self._selected_id:
            return

        self._selected_id = property_id
        self.property_selected.emit(
            property_id
        )

    def _sort_rows(
        self,
        rows: list[dict[str, Any]],
        sort_label: str,
    ) -> list[dict[str, Any]]:
        rows = list(rows)

        if sort_label == "總價低至高":
            rows.sort(
                key=lambda row:
                self._sort_number(
                    str(
                        row.get("price")
                        or ""
                    )
                )
            )

        elif sort_label == "總價高至低":
            rows.sort(
                key=lambda row: (
                    self._parse_number(
                        str(
                            row.get("price")
                            or ""
                        )
                    )
                    or -1
                ),
                reverse=True,
            )

        elif sort_label == "坪數大至小":
            rows.sort(
                key=lambda row: (
                    self._parse_number(
                        str(
                            row.get("size")
                            or ""
                        )
                    )
                    or -1
                ),
                reverse=True,
            )

        elif sort_label == "坪數小至大":
            rows.sort(
                key=lambda row:
                self._sort_number(
                    str(
                        row.get("size")
                        or ""
                    )
                )
            )

        elif sort_label == "收藏優先":
            rows.sort(
                key=lambda row: (
                    int(
                        row.get("favorite")
                        or 0
                    ),
                    str(
                        row.get("updated_at")
                        or ""
                    ),
                ),
                reverse=True,
            )

        elif sort_label == "名稱排序":
            rows.sort(
                key=lambda row:
                str(
                    row.get("title")
                    or ""
                )
            )

        else:
            rows.sort(
                key=lambda row: (
                    str(
                        row.get("updated_at")
                        or ""
                    ),
                    int(
                        row.get("id")
                        or 0
                    ),
                ),
                reverse=True,
            )

        return rows

    def _sort_number(
        self,
        value: str,
    ) -> float:
        number = self._parse_number(
            value
        )

        return (
            number
            if number is not None
            else float("inf")
        )

    @staticmethod
    def _extract_region(
        address: str,
    ) -> str:
        match = re.search(
            r"(桃園區|中壢區|平鎮區|龍潭區|楊梅區|"
            r"八德區|龜山區|蘆竹區|大溪區|大園區|"
            r"觀音區|新屋區|復興區|竹北市|新竹市|"
            r"竹東鎮|關西鎮)",
            address,
        )

        return (
            match.group(1)
            if match
            else ""
        )

    @staticmethod
    def _detect_type(
        row: dict[str, Any],
    ) -> str:
        combined = " ".join(
            str(
                row.get(key)
                or ""
            )
            for key in (
                "title",
                "address",
                "layout",
                "tag",
                "property_type",
            )
        )

        mappings = (
            (
                "土地",
                (
                    "農地",
                    "建地",
                    "工業地",
                    "土地",
                    "田",
                    "旱",
                ),
            ),
            (
                "店面",
                (
                    "店面",
                    "店住",
                    "商辦",
                ),
            ),
            (
                "廠房",
                (
                    "廠房",
                    "倉庫",
                ),
            ),
            ("別墅", ("別墅",)),
            ("透天", ("透天",)),
            (
                "大樓",
                (
                    "大樓",
                    "電梯大樓",
                ),
            ),
            ("華廈", ("華廈",)),
            ("公寓", ("公寓",)),
            ("套房", ("套房",)),
        )

        for result, keywords in mappings:
            if any(
                keyword in combined
                for keyword in keywords
            ):
                return result

        return "住宅"

    @staticmethod
    def _parse_number(
        value: str,
    ) -> float | None:
        normalized = (
            value.replace(",", "")
            .replace(" ", "")
        )

        billion_match = re.search(
            r"(\d+(?:\.\d+)?)億"
            r"(?:(\d+(?:\.\d+)?)萬)?",
            normalized,
        )

        if billion_match:
            amount = (
                float(
                    billion_match.group(1)
                )
                * 10000
            )

            if billion_match.group(2):
                amount += float(
                    billion_match.group(2)
                )

            return amount

        number_match = re.search(
            r"(\d+(?:\.\d+)?)",
            normalized,
        )

        return (
            float(
                number_match.group(1)
            )
            if number_match
            else None
        )

    @staticmethod
    def _price_matches(
        label: str,
        price: float | None,
    ) -> bool:
        if label == "全部總價":
            return True

        if price is None:
            return False

        ranges = {
            "500萬以下": (
                None,
                500,
            ),
            "500～1000萬": (
                500,
                1000,
            ),
            "1000～1500萬": (
                1000,
                1500,
            ),
            "1500～2000萬": (
                1500,
                2000,
            ),
            "2000～3000萬": (
                2000,
                3000,
            ),
            "3000萬以上": (
                3000,
                None,
            ),
        }

        lower, upper = ranges[label]

        if (
            lower is not None
            and price < lower
        ):
            return False

        if (
            upper is not None
            and price >= upper
        ):
            return False

        return True
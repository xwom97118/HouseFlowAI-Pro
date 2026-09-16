from __future__ import annotations

import re
from typing import Any


class AJCopyEngine:
    """不依賴 OpenAI 的房仲社群文案引擎 2.0。"""

    def generate(
        self,
        property_data: dict[str, Any],
        profile: dict[str, str] | None = None,
    ) -> str:
        profile = profile or {}

        title = self._text(
            property_data.get("title"),
            "精選物件",
        )
        address = self._text(
            property_data.get("address")
        )
        price = self._text(
            property_data.get("price"),
            "歡迎洽詢",
        )
        layout = self._text(
            property_data.get("layout")
        )
        size = self._text(
            property_data.get("size")
        )

        combined = " ".join(
            [title, address, layout, size]
        )
        category = self._detect_category(combined)
        features = self._extract_features(
            combined,
            layout,
            size,
            price,
        )
        region = self._extract_region(address)
        keyword = self._keyword(
            title,
            region,
            layout,
        )
        audience = self._audience(
            layout,
            price,
            category,
        )

        if category == "land":
            content = self._land_copy(
                title,
                address,
                price,
                size,
                region,
                keyword,
                features,
            )
        elif category in {"store", "factory"}:
            content = self._commercial_copy(
                title,
                address,
                price,
                layout,
                size,
                region,
                keyword,
                features,
                category,
            )
        else:
            content = self._home_copy(
                title,
                address,
                price,
                layout,
                size,
                region,
                keyword,
                features,
                audience,
                category,
            )

        cta = self._personal_cta(
            profile.get("default_cta", ""),
            keyword,
        )
        hashtags = self._hashtags(
            profile.get("default_hashtags", ""),
            region,
            category,
        )
        slogan = profile.get(
            "brand_slogan",
            "",
        ).strip()

        parts = [
            content.strip(),
            cta,
        ]

        if slogan:
            parts.append(slogan)

        if hashtags:
            parts.append(hashtags)

        return "\n\n".join(
            part
            for part in parts
            if part.strip()
        )

    def _home_copy(
        self,
        title: str,
        address: str,
        price: str,
        layout: str,
        size: str,
        region: str,
        keyword: str,
        features: list[str],
        audience: str,
        category: str,
    ) -> str:
        del keyword

        hook = self._home_hook(
            region,
            category,
            features,
            audience,
        )

        target_sentence = {
            "first_buy": (
                "如果你正在準備人生第一間房，"
                "這間可以先列入比較。"
            ),
            "family": (
                "對需要房間數、收納與生活空間的家庭來說，"
                "這類條件會更實用。"
            ),
            "premium": (
                "對重視空間感、隱私與居住品質的買方來說，"
                "真正要看的不只是總價，而是整體條件是否到位。"
            ),
            "general": (
                "買房不一定要立刻決定，"
                "但條件合適的物件值得先把資料看完整。"
            ),
        }[audience]

        feature_paragraph = self._feature_paragraph(
            features,
            category,
        )

        data_lines = [
            f"🏠【{title}】",
            f"💰 售價：{price}",
        ]

        if address:
            data_lines.append(f"📍 {address}")

        details = "｜".join(
            value
            for value in (layout, size)
            if value
        )

        if details:
            data_lines.append(f"📐 {details}")

        space_sentence = self._space_sentence(
            layout,
            size,
        )

        return "\n\n".join(
            [
                hook,
                "\n".join(data_lines),
                target_sentence,
                space_sentence,
                feature_paragraph,
                (
                    "照片可以先看屋況與空間感，"
                    "但真正適不適合，仍要把格局、動線、"
                    "周邊環境與實際需求一起比較。"
                ),
            ]
        )

    def _land_copy(
        self,
        title: str,
        address: str,
        price: str,
        size: str,
        region: str,
        keyword: str,
        features: list[str],
    ) -> str:
        del keyword

        hook = (
            f"很多人找{region or '桃園'}土地時，"
            "第一眼只看總價，但土地真正的價值，"
            "通常還要一起看位置、臨路、地形與使用條件。"
        )

        lines = [
            f"🌳【{title}】",
            f"💰 售價：{price}",
        ]

        if address:
            lines.append(f"📍 {address}")

        if size:
            lines.append(f"📐 面積：{size}")

        feature_text = (
            "、".join(features)
            if features
            else "位置與使用彈性"
        )

        return "\n\n".join(
            [
                hook,
                "\n".join(lines),
                (
                    f"這筆土地可先從「{feature_text}」"
                    "幾個方向了解。"
                ),
                (
                    "土地不能只靠照片判斷，"
                    "現場臨路寬度、地勢高低、形狀、"
                    "使用分區與是否符合需求，都要另外確認。"
                ),
            ]
        )

    def _commercial_copy(
        self,
        title: str,
        address: str,
        price: str,
        layout: str,
        size: str,
        region: str,
        keyword: str,
        features: list[str],
        category: str,
    ) -> str:
        del keyword

        label = "廠房／倉庫" if category == "factory" else "店面／商用空間"
        hook = (
            f"找{region or '桃園'}{label}，"
            "不能只看價格，位置、使用動線與空間彈性才是重點。"
        )

        lines = [
            f"🏬【{title}】",
            f"💰 售價：{price}",
        ]

        if address:
            lines.append(f"📍 {address}")

        details = "｜".join(
            value
            for value in (layout, size)
            if value
        )

        if details:
            lines.append(f"📐 {details}")

        feature_text = (
            "、".join(features)
            if features
            else "空間使用與周邊條件"
        )

        return "\n\n".join(
            [
                hook,
                "\n".join(lines),
                f"這間可先留意：{feature_text}。",
                (
                    "適合什麼產業、能否自用或收租，"
                    "仍需依現場條件、法規與實際需求評估。"
                ),
            ]
        )

    def _home_hook(
        self,
        region: str,
        category: str,
        features: list[str],
        audience: str,
    ) -> str:
        area = region or "桃園"

        if "交流道便利" in features:
            return (
                f"很多人找{area}房子時，"
                "希望空間夠用，又不想犧牲交通便利。"
                "這間主打的就是空間與交通條件。"
            )

        if "庭院" in features:
            return (
                "想找有庭院的房子，"
                "真正難的不是坪數，而是室內外空間能不能一起使用。"
                "這間值得從生活方式的角度來看。"
            )

        if category in {"villa", "house"}:
            return (
                f"很多人找{area}透天或別墅，"
                "最在意的是空間、停車與一家人的生活動線。"
                "這間可以先把完整條件看清楚。"
            )

        if audience == "first_buy":
            return (
                f"如果你正在找{area}首購物件，"
                "不要只比較總價，格局、坪數與未來使用彈性也很重要。"
            )

        if audience == "premium":
            return (
                "高總價住宅真正要看的，"
                "不是單純的坪數，而是空間是否能換來更好的生活品質。"
            )

        return (
            f"最近不少買方在找{area}條件完整、"
            "總價又能接受的住宅，這間可以先列入比較。"
        )

    @staticmethod
    def _feature_paragraph(
        features: list[str],
        category: str,
    ) -> str:
        if not features:
            return (
                "這間的重點不在單一條件，"
                "而是總價、空間與位置是否符合你的生活需求。"
            )

        joined = "、".join(features[:5])

        if category in {"villa", "house"}:
            return (
                f"從物件條件來看，可先留意：{joined}。"
                "對需要較大空間或多房配置的家庭，"
                "實際使用彈性會比一般住宅更高。"
            )

        return (
            f"這間可以先從幾個重點比較：{joined}。"
            "把這些條件和你的預算、通勤與家庭需求一起評估，"
            "會比只看照片更準確。"
        )

    @staticmethod
    def _space_sentence(
        layout: str,
        size: str,
    ) -> str:
        room_match = re.search(
            r"(\d+)\s*房",
            layout,
        )
        size_match = re.search(
            r"(\d+(?:\.\d+)?)",
            size,
        )

        room_count = (
            int(room_match.group(1))
            if room_match
            else None
        )
        area = (
            float(size_match.group(1))
            if size_match
            else None
        )

        if room_count is not None and room_count >= 5:
            return (
                f"{room_count}房的配置，"
                "不只適合大家庭或三代同堂，"
                "也能安排書房、工作室、客房或收納空間。"
            )

        if room_count == 4:
            return (
                "四房格局對換屋家庭來說更有彈性，"
                "房間用途可以依家庭成員調整。"
            )

        if room_count == 3:
            return (
                "三房是目前家庭接受度較高的格局，"
                "自住、育兒或保留工作空間都比較好安排。"
            )

        if room_count is not None and room_count <= 2:
            return (
                "房間數精簡、空間較好整理，"
                "適合首購、小家庭或希望降低居住負擔的買方。"
            )

        if area is not None and area >= 80:
            return (
                f"建物約 {area:g} 坪，"
                "空間規模明顯高於一般住宅，"
                "更需要實際確認每一層與每個區域的使用方式。"
            )

        return (
            "實際空間是否好用，"
            "還是要看格局比例、採光與生活動線。"
        )

    @staticmethod
    def _extract_features(
        combined: str,
        layout: str,
        size: str,
        price: str,
    ) -> list[str]:
        mappings = (
            ("交流道便利", ("交流道",)),
            ("庭院", ("庭院", "花園")),
            ("雙車位", ("雙車", "雙車位", "2車位")),
            ("車庫", ("車庫",)),
            ("景觀視野", ("景觀", "視野")),
            ("邊間", ("邊間",)),
            ("採光", ("採光", "明亮")),
            ("裝潢", ("裝潢", "整理")),
            ("近學區", ("學區", "國小", "國中")),
            ("市中心機能", ("市中心", "商圈")),
            ("電梯", ("電梯",)),
            ("近龍科", ("龍科", "科學園區")),
            ("大坪數", ("大坪數",)),
        )

        features: list[str] = []

        for label, keywords in mappings:
            if any(
                keyword in combined
                for keyword in keywords
            ):
                features.append(label)

        size_number = AJCopyEngine._number(size)
        price_number = AJCopyEngine._price_number(price)
        room_match = re.search(
            r"(\d+)\s*房",
            layout,
        )

        if size_number is not None and size_number >= 60:
            if "大坪數" not in features:
                features.append("大坪數")

        if room_match and int(room_match.group(1)) >= 4:
            features.append("多房配置")

        if price_number is not None and price_number < 1000:
            features.append("千萬內總價")

        return list(dict.fromkeys(features))[:6]

    @staticmethod
    def _audience(
        layout: str,
        price: str,
        category: str,
    ) -> str:
        if category in {"land", "store", "factory"}:
            return "general"

        price_number = AJCopyEngine._price_number(
            price
        )

        if price_number is not None:
            if price_number < 1000:
                return "first_buy"

            if price_number >= 2500:
                return "premium"

        room_match = re.search(
            r"(\d+)\s*房",
            layout,
        )

        if room_match and int(room_match.group(1)) >= 3:
            return "family"

        return "general"

    @staticmethod
    def _detect_category(text: str) -> str:
        if any(
            word in text
            for word in ("農地", "建地", "工業地", "土地", "田", "旱")
        ):
            return "land"

        if any(
            word in text
            for word in ("廠房", "倉庫")
        ):
            return "factory"

        if any(
            word in text
            for word in ("店面", "店住", "商辦", "辦公")
        ):
            return "store"

        if "別墅" in text:
            return "villa"

        if "透天" in text:
            return "house"

        return "home"

    @staticmethod
    def _extract_region(address: str) -> str:
        match = re.search(
            r"(桃園區|中壢區|平鎮區|龍潭區|楊梅區|"
            r"八德區|龜山區|蘆竹區|大溪區|大園區|"
            r"觀音區|新屋區|復興區|竹北市|新竹市|"
            r"竹東鎮|關西鎮)",
            address,
        )
        return match.group(1) if match else ""

    @staticmethod
    def _keyword(
        title: str,
        region: str,
        layout: str,
    ) -> str:
        cleaned = re.sub(
            r"[^\u4e00-\u9fffA-Za-z0-9]",
            "",
            title,
        )

        for keyword in (
            "高原",
            "幸福山丘",
            "百年大鎮",
            "龍科",
        ):
            if keyword in title:
                return keyword[:4]

        room = re.search(
            r"(\d+)\s*房",
            layout,
        )

        if room:
            return f"{room.group(1)}房"

        if region:
            return region.replace("區", "")

        return cleaned[:4] or "賞屋"

    @staticmethod
    def _personal_cta(
        saved_cta: str,
        keyword: str,
    ) -> str:
        if saved_cta:
            cta = saved_cta.strip()
            cta = cta.replace(
                "「賞屋」",
                f"「{keyword}」",
            )
            cta = cta.replace(
                '"賞屋"',
                f'"{keyword}"',
            )
            return cta

        return (
            f"想看完整照片、物件資料或安排現場，"
            f"留言「{keyword}」，我直接傳給你。"
        )

    @staticmethod
    def _hashtags(
        saved: str,
        region: str,
        category: str,
    ) -> str:
        tags = [
            line.strip()
            for line in saved.replace(" ", "\n").splitlines()
            if line.strip().startswith("#")
        ]

        if not tags:
            tags = [
                "#不動產買賣",
                "#房地產",
            ]

        if region:
            tags.append(
                f"#{region.replace('區', '')}房地產"
            )

        category_tag = {
            "land": "#土地買賣",
            "store": "#店面",
            "factory": "#廠房",
            "villa": "#別墅",
            "house": "#透天",
            "home": "#買房",
        }.get(category)

        if category_tag:
            tags.append(category_tag)

        return " ".join(
            list(dict.fromkeys(tags))[:8]
        )

    @staticmethod
    def _price_number(value: str) -> float | None:
        normalized = (
            value.replace(",", "")
            .replace(" ", "")
        )
        billion = re.search(
            r"(\d+(?:\.\d+)?)億"
            r"(?:(\d+(?:\.\d+)?)萬)?",
            normalized,
        )

        if billion:
            amount = float(billion.group(1)) * 10000

            if billion.group(2):
                amount += float(billion.group(2))

            return amount

        return AJCopyEngine._number(normalized)

    @staticmethod
    def _number(value: str) -> float | None:
        match = re.search(
            r"(\d+(?:\.\d+)?)",
            value.replace(",", ""),
        )
        return float(match.group(1)) if match else None

    @staticmethod
    def _text(
        value: Any,
        default: str = "",
    ) -> str:
        text = str(
            value
            if value is not None
            else ""
        ).strip()
        return text or default
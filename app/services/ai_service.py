from __future__ import annotations

import os
from typing import Any

# 2026-09-22 產品化 Phase 1.1：STYLE_MAP 原本第一個選項寫死
# 「阿嘉在地風」，描述文字裡也直接寫「阿嘉本人」——HouseFlow 已經是要
# 給其他房仲使用的通用商業軟體，風格描述不應該綁死開發時測試帳號的
# 名字。改成通用的「在地親切風」，語氣描述本身保留（在地、親切、口語
# 自然），只是不再指名道姓。
class AIService:
    STYLE_MAP = {
        "在地親切風": "在地、親切、口語自然、直接講重點，像熟悉當地的房仲本人說話",
        "專業分析": "理性、專業、清楚分析房產條件與適合客群",
        "精簡有力": "短句、強勾子、快速抓重點，避免冗長",
        "生活感": "描述實際居住情境、生活機能與家庭使用感受",
    }

    def __init__(self, model: str = "gpt-5.5") -> None:
        self.model = model

        api_key = os.getenv("OPENAI_API_KEY", "").strip()

        if not api_key:
            raise RuntimeError(
                "尚未設定 OPENAI_API_KEY。"
                "請先在 Windows 環境變數加入 API Key，"
                "再重新啟動 VS Code。"
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "尚未安裝 OpenAI 套件，但不影響其他功能。請重新執行安裝程式。"
            ) from exc

        self.client = OpenAI(api_key=api_key)

    def generate(
        self,
        property_data: dict[str, Any],
        platform: str,
        style: str,
        extra: str = "",
        brand_profile: dict[str, Any] | None = None,
    ) -> str:
        """brand_profile 對應 app.services.brand_profile.load_profile() 的
        回傳值（display_name / brand_slogan / default_cta /
        default_hashtags…）——呼叫端（app/pages/ai_center.py）負責從目前
        使用者在設定頁填寫的資料組出這個 dict，AIService 本身不寫死任何
        特定使用者的姓名或地區（見 2026-09-22 產品化 Phase 1.1）。
        """
        property_text = self._build_property_text(property_data)
        style_description = self.STYLE_MAP.get(style, style)

        instructions = (
            "你是台灣不動產社群行銷文案專家。"
            "使用繁體中文，文字自然，不要像制式 AI 文案。"
            "不得捏造物件沒有提供的設備、學區、交通、屋齡、"
            "貸款條件、投報率或生活機能。"
            "遇到缺少的資料就省略，不要自行猜測。"
            "文案要符合台灣房仲實際使用情境。"
        )

        prompt = self._build_prompt(
            platform=platform,
            property_text=property_text,
            style_description=style_description,
            extra=extra,
            brand_profile=brand_profile,
        )

        response = self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=prompt,
        )

        content = response.output_text.strip()

        if not content:
            raise RuntimeError("AI 沒有回傳文案，請稍後再試。")

        return content

    @staticmethod
    def _build_brand_block(brand_profile: dict[str, Any] | None) -> str:
        """組出「固定品牌資訊」區塊，內容完全來自使用者在設定頁填寫的
        資料（app.services.brand_profile.load_profile()），不寫死任何
        特定使用者的姓名、地區或 Hashtag。使用者還沒填寫時，明確告訴
        AI 不要自己捏造姓名或地區，而不是留下一個看起來很正式、實際上
        是假資料的區塊。
        """
        profile = brand_profile or {}
        display_name = str(profile.get("display_name", "") or "").strip()
        slogan = str(profile.get("brand_slogan", "") or profile.get("service_area", "") or "").strip()
        cta = str(profile.get("default_cta", "") or "").strip() or "想了解更多，歡迎私訊，我帶你實際看看。"
        hashtags = str(profile.get("default_hashtags", "") or "").strip()

        lines = []
        if display_name:
            lines.append(f"姓名／品牌名稱：{display_name}")
        if slogan:
            lines.append(f"品牌定位／服務區域：{slogan}")
        lines.append(f"常用結尾：{cta}")
        if hashtags:
            lines.append(f"常用 Hashtag：{hashtags}")

        if not display_name and not slogan and not hashtags:
            return (
                "固定品牌資訊：\n"
                "（使用者尚未在設定頁填寫品牌資訊，請不要自行捏造姓名、公司或地區，"
                "只根據上方物件資料撰寫文案，結尾可使用下面這句通用行動呼籲。）\n"
                f"常用結尾：{cta}"
            )

        return "固定品牌資訊：\n" + "\n".join(lines)

    def _build_property_text(
        self,
        property_data: dict[str, Any],
    ) -> str:
        fields = [
            ("物件名稱", property_data.get("title")),
            ("售價", property_data.get("price")),
            ("地址", property_data.get("address")),
            ("格局", property_data.get("layout")),
            ("坪數", property_data.get("size")),
            ("物件編號", property_data.get("external_id")),
            ("原始網址", property_data.get("url")),
        ]

        lines = []

        for label, value in fields:
            text = str(value or "").strip()

            if text:
                lines.append(f"{label}：{text}")

        return "\n".join(lines)

    def _build_prompt(
        self,
        platform: str,
        property_text: str,
        style_description: str,
        extra: str,
        brand_profile: dict[str, Any] | None = None,
    ) -> str:
        brand_block = self._build_brand_block(brand_profile)

        common = f"""
請根據以下真實物件資料撰寫內容：

{property_text}

文案風格：
{style_description}

使用者補充要求：
{extra or "無"}

{brand_block}
""".strip()

        platform_rules = {
            "Facebook": """
請寫一篇 Facebook 貼文。

要求：
1. 開頭要有能吸引買方停下來看的勾子。
2. 清楚列出售價、地點、格局、坪數。
3. 用段落和少量 Emoji，保持容易閱讀。
4. 補充適合的買方族群，但不可過度推論。
5. 結尾加入行動呼籲。
6. 最後加入 5 至 8 個相關 Hashtag。
7. 不要使用「夢想宅」、「錯過不再」等浮誇罐頭詞。
""",
            "Instagram": """
請寫一篇 Instagram 貼文。

要求：
1. 第一行要適合當圖片貼文標題。
2. 內容比 Facebook 精簡。
3. 使用短段落與適量 Emoji。
4. 清楚呈現物件重點。
5. 結尾加入私訊或預約賞屋 CTA。
6. 最後加入 8 至 12 個相關 Hashtag。
""",
            "Threads": """
請寫一篇 Threads 貼文。

要求：
1. 像真人分享，不要像廣告型錄。
2. 口語、精簡、有觀點。
3. 先講最值得注意的條件。
4. 控制在約 250 個中文字內。
5. 最後自然邀請讀者私訊。
6. Hashtag 最多 2 個。
""",
            "Reels 15秒": """
請寫一支 15 秒 Reels 口播腳本。

格式：
【0-3 秒｜勾子】
【3-10 秒｜物件重點】
【10-15 秒｜CTA】

要求：
1. 台詞必須能在 15 秒內自然講完。
2. 適合房仲對鏡頭直接口播。
3. 同時附上 3 個畫面建議。
4. 最後提供一個封面標題，10 字以內。
""",
            "Reels 30秒": """
請寫一支 30 秒 Reels 口播腳本。

格式：
【0-3 秒｜勾子】
【3-20 秒｜三個物件重點】
【20-27 秒｜適合客群】
【27-30 秒｜CTA】

要求：
1. 台詞自然，適合房仲口播。
2. 每一段附上畫面或運鏡建議。
3. 最後提供一個封面標題，10 字以內。
""",
            "Reels 60秒": """
請寫一支 60 秒 Reels 物件介紹腳本。

格式：
【0-5 秒｜勾子】
【5-15 秒｜基本資料】
【15-40 秒｜三至四個主要特色】
【40-50 秒｜適合客群】
【50-60 秒｜CTA】

要求：
1. 台詞自然，不要像逐條念規格。
2. 每段附畫面或運鏡建議。
3. 不可捏造未提供的物件特色。
4. 最後提供封面標題與貼文短文各一份。
""",
        }

        rule = platform_rules.get(
            platform,
            "請依照指定平台撰寫合適的不動產文案。",
        )

        return f"{common}\n\n平台任務：\n{rule.strip()}"
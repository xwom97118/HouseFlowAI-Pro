"""AIService 品牌資訊不再寫死開發時測試帳號的回歸測試（2026-09-22
產品化 Phase 1.1）。

Audit 發現 app/services/ai_service.py 的 STYLE_MAP 與固定品牌資訊區塊
直接寫死「阿嘉」「龍潭」——HouseFlow 已經是要給其他房仲使用的商業
軟體，這些字串不應該出現在任何 prompt 或使用者看得到的風格選單裡。
這裡只測試 AIService 的純邏輯部分（STYLE_MAP、_build_brand_block、
_build_prompt 組字串），完全不需要 OPENAI_API_KEY、不會真的打 API。
"""
from __future__ import annotations

from app.services.ai_service import AIService


def test_style_map_has_no_hardcoded_persona_name() -> None:
    for key, description in AIService.STYLE_MAP.items():
        assert "阿嘉" not in key
        assert "阿嘉" not in description
        assert "龍潭" not in key
        assert "龍潭" not in description


def test_brand_block_with_no_profile_has_no_fake_identity() -> None:
    block = AIService._build_brand_block(None)
    assert "阿嘉" not in block
    assert "龍潭" not in block
    assert "尚未在設定頁填寫" in block  # 明確告訴 AI 不要自己捏造


def test_brand_block_with_empty_dict_behaves_same_as_none() -> None:
    block_none = AIService._build_brand_block(None)
    block_empty = AIService._build_brand_block({})
    assert block_none == block_empty


def test_brand_block_uses_configured_display_name() -> None:
    block = AIService._build_brand_block({"display_name": "測試房仲小美"})
    assert "測試房仲小美" in block
    assert "阿嘉" not in block


def test_brand_block_uses_configured_slogan_and_hashtags() -> None:
    block = AIService._build_brand_block(
        {
            "display_name": "測試房仲",
            "brand_slogan": "新竹在地服務",
            "default_hashtags": "#新竹房屋 #測試標籤",
        }
    )
    assert "新竹在地服務" in block
    assert "#新竹房屋 #測試標籤" in block
    assert "龍潭" not in block


def test_brand_block_falls_back_to_service_area_when_no_slogan() -> None:
    block = AIService._build_brand_block({"display_name": "測試房仲", "service_area": "台中北屯"})
    assert "台中北屯" in block


def test_brand_block_has_generic_default_cta_when_unset() -> None:
    block = AIService._build_brand_block({"display_name": "測試房仲"})
    assert "想了解更多，歡迎私訊，我帶你實際看看。" in block


def test_brand_block_uses_configured_cta_when_set() -> None:
    block = AIService._build_brand_block({"default_cta": "歡迎預約賞屋，line我就可以！"})
    assert "歡迎預約賞屋，line我就可以！" in block


def test_build_prompt_does_not_leak_hardcoded_identity() -> None:
    """完整組一次 prompt（不呼叫 OpenAI），確認整份文字裡沒有任何
    開發時測試帳號的個人資訊，即使呼叫端沒有傳入 brand_profile。
    """
    service = AIService.__new__(AIService)  # 跳過 __init__（避免需要 OPENAI_API_KEY）
    prompt = service._build_prompt(
        platform="Facebook",
        property_text="物件名稱：測試物件\n售價：888萬",
        style_description="在地、親切、口語自然",
        extra="",
        brand_profile=None,
    )
    assert "阿嘉" not in prompt
    assert "龍潭" not in prompt


if __name__ == "__main__":
    import sys

    failures = 0
    tests = [(name, obj) for name, obj in list(globals().items()) if name.startswith("test_")]
    for name, test in tests:
        try:
            test()
            print(f"PASS: {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL: {name}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)

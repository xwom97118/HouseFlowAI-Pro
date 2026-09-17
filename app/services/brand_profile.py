from __future__ import annotations

from typing import Any

from app.services.database import Database

# 品牌欄位沿用既有 app_settings key（settings.py 原本就在用這些）。
BRAND_KEYS = {
    "display_name": "display_name",
    "service_area": "service_area",
    "brand_slogan": "brand_slogan",
    "phone": "agent_phone",
    "line_id": "line_id",
    "email": "agent_email",
    "default_cta": "default_cta",
    "default_hashtags": "default_hashtags",
}

# 經紀業法定資訊：新欄位。
BROKERAGE_KEYS = {
    "brokerage_name": "brokerage_name",
    "salesperson_name": "salesperson_name",
    "salesperson_license": "salesperson_license",
    "broker_name": "broker_name",
    "broker_license": "broker_license",
    "company_address": "company_address",
    "company_phone": "company_phone",
}

FOOTER_DIVIDER = "─" * 16

# 經紀業合規資訊是否完整所需的最低欄位（姓名可選，證號與經紀業名稱必填）。
REQUIRED_COMPLIANCE_KEYS = ("brokerage_name", "salesperson_license", "broker_license")


def load_profile(db: Database) -> dict[str, str]:
    """讀取品牌 + 經紀業設定為單一 dict，供文案產生與排程使用。"""
    profile: dict[str, str] = {}
    for field, setting_key in {**BRAND_KEYS, **BROKERAGE_KEYS}.items():
        profile[field] = db.get_setting(setting_key, "").strip()
    return profile


def is_compliance_complete(profile: dict[str, str]) -> bool:
    return all(str(profile.get(key, "")).strip() for key in REQUIRED_COMPLIANCE_KEYS)


def missing_compliance_labels(profile: dict[str, str]) -> list[str]:
    labels = {
        "brokerage_name": "經紀業名稱",
        "salesperson_license": "營業員證號",
        "broker_license": "經紀人證號",
    }
    return [
        labels[key]
        for key in REQUIRED_COMPLIANCE_KEYS
        if not str(profile.get(key, "")).strip()
    ]


def format_compliance_footer(profile: dict[str, str]) -> str:
    """組出固定格式的經紀業合規資訊區塊；資訊不足時回傳空字串（不顯示半吊子區塊）。"""
    if not is_compliance_complete(profile):
        return ""

    brokerage_name = str(profile.get("brokerage_name", "")).strip()
    salesperson_name = str(profile.get("salesperson_name", "")).strip()
    salesperson_license = str(profile.get("salesperson_license", "")).strip()
    broker_name = str(profile.get("broker_name", "")).strip()
    broker_license = str(profile.get("broker_license", "")).strip()

    salesperson_line = (
        f"營業員：{salesperson_name}｜{salesperson_license}"
        if salesperson_name
        else f"營業員：{salesperson_license}"
    )
    broker_line = (
        f"經紀人：{broker_name}｜{broker_license}"
        if broker_name
        else f"經紀人：{broker_license}"
    )

    lines = [
        FOOTER_DIVIDER,
        f"經紀業：{brokerage_name}",
        salesperson_line,
        broker_line,
    ]
    return "\n".join(lines)


def insert_or_replace_compliance_footer(text: str, profile: dict[str, str]) -> str:
    """把文字中既有的經紀業合規區塊移除（如果有），再把最新版本接到結尾。

    用來避免使用者重複按「插入經紀業資訊」時越疊越多份；不是每次都直接
    append，而是先找出、移除舊區塊，才貼上新的一份。
    """
    footer = format_compliance_footer(profile)

    blocks = [block for block in text.split("\n\n")]
    filtered_blocks = [
        block for block in blocks if not block.strip().startswith(FOOTER_DIVIDER)
    ]

    result_text = "\n\n".join(block for block in filtered_blocks if block.strip())

    if not footer:
        return result_text

    if result_text:
        return f"{result_text}\n\n{footer}"
    return footer

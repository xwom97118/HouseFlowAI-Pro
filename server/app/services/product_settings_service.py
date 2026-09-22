from __future__ import annotations

from sqlalchemy.orm import Session

from server.app.models.license import ProductSettings


def get_product_settings(db: Session) -> ProductSettings:
    """讀取（或第一次呼叫時建立）全域商業設定單一列。"""
    settings = db.get(ProductSettings, 1)
    if settings is None:
        settings = ProductSettings(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_product_settings(db: Session, **fields) -> ProductSettings:
    settings = get_product_settings(db)
    for key, value in fields.items():
        if value is not None and hasattr(settings, key):
            setattr(settings, key, value)
    db.commit()
    db.refresh(settings)
    return settings

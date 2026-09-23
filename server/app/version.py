"""License Server 自己的版本號——跟 Desktop 的 app/version.py
（APP_VERSION，指 HouseFlow Desktop 應用程式本身的版本）是兩個獨立的
概念，不要混用。這個版本號單純代表 License Server 這個服務本身的
版本，用於 /health 回應與內部診斷。"""
from __future__ import annotations

SERVER_VERSION = "0.1.0"

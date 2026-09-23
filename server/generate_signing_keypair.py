"""產生一組全新的 Ed25519 License 狀態簽章金鑰對（2026-09-23 Phase
3A，規格第 20 節）。

用法：

    python server/generate_signing_keypair.py

輸出兩個值：
- 私鑰（base64，設成 server 端環境變數 HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY）
- 公鑰（base64，設成 Desktop 端環境變數 HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY）

私鑰絕對不能 commit 進 git、不能貼在任何文件或聊天記錄裡——只存在
Render 的環境變數設定（或其他你選擇的 secret 管理方式）。公鑰可以
安全地放進 Desktop 安裝檔或公開文件，外流沒有安全疑慮（只能拿來
「驗證」簽章，不能拿來「偽造」簽章）。

這支腳本本身不會把任何東西寫進檔案或資料庫，純粹印出來給你自己複製
貼上到環境變數設定介面。
"""
from __future__ import annotations

import base64
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> int:
    private_key = Ed25519PrivateKey.generate()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_b64 = base64.b64encode(private_pem).decode("ascii")

    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_b64 = base64.b64encode(public_bytes).decode("ascii")

    print("=" * 70)
    print("HouseFlow License Server 簽章金鑰對（新產生，尚未使用過）")
    print("=" * 70)
    print()
    print("[Server 端環境變數 - 絕對不要 commit、不要分享]")
    print(f"HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY={private_b64}")
    print()
    print("[Desktop 端環境變數 - 可以安全公開]")
    print(f"HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY={public_b64}")
    print()
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())

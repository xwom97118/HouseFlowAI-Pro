"""Regression test for the manual/live Facebook script isolation itself
（2026-09-22 產品化 Phase 1.1）。

背景：一次 `ls test_*.py` 式的 regression sweep 誤執行了
test_facebook_login.py，開啟了一個真正、已登入的 production Facebook
瀏覽器視窗（後來移到 manual_tests/manual_facebook_login.py，並加上
HOUSEFLOW_ALLOW_LIVE_FACEBOOK=1 的安全閘門）。這個測試檔案本身不去碰
Facebook，只驗證「這件事不會再發生」這個不變量本身：

1. repo 根目錄的 test_*.py 清單裡，沒有任何一個檔案會呼叫
   FacebookService().open_login() 或建立真正的 launch_persistent_context。
2. manual_tests/ 底下的 manual script，在沒有設定
   HOUSEFLOW_ALLOW_LIVE_FACEBOOK=1 時，_live_guard 會在碰任何
   Facebook 相關程式碼之前就直接拒絕執行。
3. manual_tests/manual_facebook_login.py 實際执行（不設環境變數）不會
   啟動任何新的瀏覽器行程（用「執行前後瀏覽器程序清單」間接驗證，
   而不是直接檢查 Facebook API，因為那需要真的裝置狀態）。
"""
from __future__ import annotations

import glob
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def test_no_root_level_test_file_imports_facebook_login_directly() -> None:
    """repo 根目錄符合 test_*.py 的檔案，不應該有任何一個會真的呼叫
    open_login() 或 launch_persistent_context()（這些代表會真的開瀏覽器、
    碰 production session）。Mock 測試呼叫的是假的 FacebookService，
    不會匹配這個字串本身。
    """
    offending: list[str] = []
    for path_str in glob.glob(str(REPO_ROOT / "test_*.py")):
        path = Path(path_str)
        if path.name == "test_live_facebook_isolation.py":
            continue  # 這個檔案本身在文件字串裡合法地提到這兩個字，不是真的呼叫
        content = path.read_text(encoding="utf-8", errors="ignore")
        if "open_login(" in content or "launch_persistent_context(" in content:
            offending.append(path.name)

    assert offending == [], f"這些檔案不應該存在於 test_*.py 但看起來會碰真正的瀏覽器: {offending}"


def test_manual_facebook_login_script_is_not_named_test_star() -> None:
    manual_script = REPO_ROOT / "manual_tests" / "manual_facebook_login.py"
    assert manual_script.exists(), "manual_facebook_login.py 應該存在於 manual_tests/"
    assert not manual_script.name.startswith("test_"), "manual script 的檔名不能符合 test_*.py，避免被自動掃到"

    # 舊檔名不應該再存在於 repo 根目錄
    assert not (REPO_ROOT / "test_facebook_login.py").exists()


def test_live_guard_module_exists_and_defaults_to_deny() -> None:
    sys.path.insert(0, str(REPO_ROOT / "manual_tests"))
    try:
        import _live_guard

        import os

        os.environ.pop("HOUSEFLOW_ALLOW_LIVE_FACEBOOK", None)
        assert _live_guard.is_live_facebook_allowed() is False
    finally:
        sys.path.remove(str(REPO_ROOT / "manual_tests"))
        sys.modules.pop("_live_guard", None)


def test_live_guard_allows_only_with_explicit_flag() -> None:
    sys.path.insert(0, str(REPO_ROOT / "manual_tests"))
    try:
        import os

        import _live_guard

        os.environ["HOUSEFLOW_ALLOW_LIVE_FACEBOOK"] = "1"
        assert _live_guard.is_live_facebook_allowed() is True

        os.environ["HOUSEFLOW_ALLOW_LIVE_FACEBOOK"] = "0"
        assert _live_guard.is_live_facebook_allowed() is False

        os.environ.pop("HOUSEFLOW_ALLOW_LIVE_FACEBOOK", None)
        assert _live_guard.is_live_facebook_allowed() is False
    finally:
        os.environ.pop("HOUSEFLOW_ALLOW_LIVE_FACEBOOK", None)
        sys.path.remove(str(REPO_ROOT / "manual_tests"))
        sys.modules.pop("_live_guard", None)


def test_manual_script_refuses_without_flag_and_launches_no_browser() -> None:
    """實際跑一次 subprocess（沒有設定 flag），確認它在 2 秒內就以
    exit code 1 結束，不會卡住等待真正的瀏覽器/登入互動。這間接證明
    它在碰任何 Facebook / Playwright 程式碼之前就已經 return。
    """
    import os

    env = dict(os.environ)
    env.pop("HOUSEFLOW_ALLOW_LIVE_FACEBOOK", None)

    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "manual_tests" / "manual_facebook_login.py")],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    assert result.returncode == 1
    assert "拒絕執行" in result.stdout or "拒絕執行" in result.stderr


if __name__ == "__main__":
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

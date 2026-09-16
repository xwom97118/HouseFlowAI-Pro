from app.services.browser_runtime import ensure_playwright_browsers_path

ensure_playwright_browsers_path()

from app.application import run

if __name__ == "__main__":
    run()

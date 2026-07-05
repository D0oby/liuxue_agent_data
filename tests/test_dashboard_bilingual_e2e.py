from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
import unittest
import urllib.request

from playwright.sync_api import expect, sync_playwright


RUN_E2E = os.getenv("RUN_DASHBOARD_E2E") == "1"


@unittest.skipUnless(RUN_E2E, "Set RUN_DASHBOARD_E2E=1 to run headed Playwright dashboard smoke tests.")
class DashboardBilingualE2ETests(unittest.TestCase):
    process: subprocess.Popen[str] | None = None
    base_url: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.base_url = os.getenv("DASHBOARD_E2E_URL") or f"http://localhost:{_free_port()}"
        if os.getenv("DASHBOARD_E2E_URL"):
            _wait_for_dashboard(cls.base_url)
            return

        port = cls.base_url.rsplit(":", 1)[1]
        cls.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "src/dashboard.py",
                "--server.port",
                port,
                "--server.headless",
                "true",
                "--server.runOnSave",
                "false",
            ],
            cwd=os.getcwd(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        _wait_for_dashboard(cls.base_url)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.process is not None:
            cls.process.terminate()
            try:
                cls.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.process.kill()

    def test_dashboard_language_switch_is_visible_and_session_scoped(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                page = browser.new_page()
                page.goto(self.base_url, wait_until="domcontentloaded")

                expect(page.get_by_text("USYD Recommendation Console", exact=True)).to_be_visible(timeout=20_000)
                expect(page.get_by_text("Recommendation Plan", exact=True)).to_be_visible()
                expect(page.get_by_text("Course Search", exact=True)).to_be_visible()
                expect(page.get_by_role("link", name="Docs")).to_have_attribute("href", re.compile(r"README\.md"))

                page.get_by_text("中文", exact=True).click()

                expect(page.get_by_text("USYD 留学方案工作台", exact=True)).to_be_visible(timeout=10_000)
                expect(page.get_by_text("推荐方案", exact=True)).to_be_visible()
                expect(page.get_by_role("link", name="文档")).to_have_attribute("href", re.compile(r"README\.zh\.md"))

                page.get_by_text("课程查询", exact=True).click()

                expect(page.get_by_text("录取要求语义搜索", exact=True)).to_be_visible(timeout=10_000)
                expect(page.get_by_text("USYD 留学方案工作台", exact=True)).to_be_visible()
            finally:
                browser.close()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_dashboard(base_url: str) -> None:
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url, timeout=2) as response:
                if response.status < 500:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"Dashboard did not become ready at {base_url}")


if __name__ == "__main__":
    unittest.main()

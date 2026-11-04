#!/usr/bin/env python3
# Copyright (c) 2023 tecnovert
# Copyright (c) 2024-2025 The Basicswap developers
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

import os
import sys
from pathlib import Path

from selenium.webdriver.common.by import By

BSX_0_PORT = int(os.getenv("BSX_0_PORT", "12701"))
BSX_1_PORT = int(os.getenv("BSX_1_PORT", str(BSX_0_PORT + 1)))
BSX_2_PORT = int(os.getenv("BSX_1_PORT", str(BSX_0_PORT + 2)))

# Default to headless Chromium DOM so wallet/UI tests never pop up windows or steal focus.
BSX_SELENIUM_DRIVER = os.getenv("BSX_SELENIUM_DRIVER", "chrome")


def _allow_headed() -> bool:
    if os.getenv("BSX_HEADED") != "1" and os.getenv("HEADED") != "1":
        return False
    return not (
        (os.getenv("ANTIGRAVITY_AGENT") or os.getenv("CLAUDECODE"))
        and os.getenv("HUMAN_HEADED_OK") != "1"
    )


def _find_chromium_binary(headed: bool) -> str | None:
    explicit = (
        os.getenv("BSX_CHROME_BINARY")
        or os.getenv("E2E_CHROMIUM")
        or os.getenv("CHROMIUM_PATH")
    )
    if explicit:
        return explicit
    cache = Path(
        os.getenv("PLAYWRIGHT_BROWSERS_PATH")
        or (
            Path.home() / "Library/Caches/ms-playwright"
            if sys.platform == "darwin"
            else Path.home() / ".cache/ms-playwright"
        )
    )
    if not cache.is_dir():
        return None
    if not headed:
        shells = sorted(
            (d for d in cache.iterdir() if d.name.startswith("chromium_headless_shell-")),
            key=lambda p: int(p.name.rsplit("-", 1)[-1]) if p.name.rsplit("-", 1)[-1].isdigit() else 0,
            reverse=True,
        )
        for d in shells:
            for rel in (
                "chrome-headless-shell-mac-arm64/chrome-headless-shell",
                "chrome-headless-shell-mac-x64/chrome-headless-shell",
                "chrome-headless-shell-linux64/chrome-headless-shell",
                "chrome-linux/headless_shell",
            ):
                cand = d / rel
                if cand.is_file():
                    return str(cand)
    browsers = sorted(
        (d for d in cache.iterdir() if d.name.startswith("chromium-")),
        key=lambda p: int(p.name.rsplit("-", 1)[-1]) if p.name.rsplit("-", 1)[-1].isdigit() else 0,
        reverse=True,
    )
    for d in browsers:
        for rel in (
            "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
            "chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
            "chrome-linux64/chrome",
            "chrome-linux/chrome",
        ):
            cand = d / rel
            if cand.is_file():
                return str(cand)
    return None


def get_driver():
    headed = _allow_headed()
    if BSX_SELENIUM_DRIVER in ("chrome", "chromium", "chrome-ci"):
        from selenium.webdriver import Chrome, ChromeOptions

        options = ChromeOptions()
        binary = _find_chromium_binary(headed)
        if binary:
            options.binary_location = binary
        if not headed or BSX_SELENIUM_DRIVER == "chrome-ci":
            if not (binary and "headless-shell" in binary):
                options.add_argument("--headless=new")
            options.add_argument("--hide-scrollbars")
            options.add_argument("--mute-audio")
            options.add_argument("--no-sandbox")
            options.add_argument("--window-size=1920,1080")
        driver = Chrome(options=options)
    elif BSX_SELENIUM_DRIVER in ("firefox", "firefox-ci"):
        from selenium.webdriver import Firefox, FirefoxOptions

        options = FirefoxOptions()
        if not headed or BSX_SELENIUM_DRIVER == "firefox-ci":
            options.add_argument("-headless")
            options.add_argument("--width=1920")
            options.add_argument("--height=1080")
        driver = Firefox(options=options)
    elif BSX_SELENIUM_DRIVER == "safari":
        from selenium.webdriver import Safari, SafariOptions

        driver = Safari(options=SafariOptions())
    else:
        raise ValueError("Unknown driver " + BSX_SELENIUM_DRIVER)
    return driver


def click_option(el, option_text):
    for option in el.find_elements(By.TAG_NAME, "option"):
        if option.text == option_text:
            option.click()
            break

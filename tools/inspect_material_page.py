from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=Path(".data/web-probe-profile"),
            channel="msedge",
            headless=True,
            locale="zh-CN",
        )
        page = context.pages[0]
        page.goto(
            "https://zy-eclass.bit.edu.cn/course/20109/courseware",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        page.wait_for_timeout(8_000)
        rows = page.locator("a,button").evaluate_all(
            """
            (elements) => elements
              .map((element) => ({
                text: (element.innerText || element.title || "").trim(),
                href: element.href || "",
                className: element.className || "",
                outerHTML: element.outerHTML.slice(0, 800),
              }))
              .filter((item) => item.text.includes("下载") || item.href.includes("download"))
            """
        )
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        context.close()


if __name__ == "__main__":
    main()

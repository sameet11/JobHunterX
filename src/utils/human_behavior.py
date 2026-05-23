"""Human-speed delays, typing, scrolling, and clicking for Playwright pages.

Reused by Phase 2 (LinkedIn applier) and Phase 3 (LinkedIn outreach).
Uses gaussian-ish distributions so timing isn't suspiciously uniform.
"""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from config.user_config import HumanSpeed


def _gauss_ms(min_ms: int, max_ms: int) -> float:
    """Return a delay (in seconds) skewed toward the middle of [min, max]."""
    mean = (min_ms + max_ms) / 2
    stdev = (max_ms - min_ms) / 6
    raw = random.gauss(mean, stdev)
    clamped = max(min_ms, min(max_ms, raw))
    return clamped / 1000


class HumanBehavior:
    def __init__(self, speed: HumanSpeed | None = None) -> None:
        self.speed = speed or HumanSpeed()

    async def pause(self, min_ms: int | None = None, max_ms: int | None = None) -> None:
        delay = _gauss_ms(
            min_ms if min_ms is not None else self.speed.min_delay_ms,
            max_ms if max_ms is not None else self.speed.max_delay_ms,
        )
        await asyncio.sleep(delay)

    async def short_pause(self) -> None:
        await asyncio.sleep(_gauss_ms(200, 700))

    async def reading_pause(self, text: str = "") -> None:
        words = max(20, len(text.split()))
        ms = min(8000, words * 200 + random.randint(-300, 600))
        await asyncio.sleep(ms / 1000)

    async def type_text(self, page: "Page", selector: str, text: str) -> None:
        await page.click(selector)
        await self.short_pause()
        for char in text:
            await page.keyboard.type(char)
            ms_per_char = 60_000 / (self.speed.typing_wpm * 5)
            await asyncio.sleep((ms_per_char + random.randint(-30, 60)) / 1000)
            if random.random() < 0.02:
                await asyncio.sleep(0.4)
                await page.keyboard.press("Backspace")
                await asyncio.sleep(0.2)
                await page.keyboard.type(char)

    async def human_click(self, page: "Page", selector: str) -> None:
        element = await page.wait_for_selector(selector, timeout=10_000)
        if not element:
            raise RuntimeError(f"Element not found: {selector}")
        box = await element.bounding_box()
        if box:
            x = box["x"] + box["width"] / 2 + random.uniform(-5, 5)
            y = box["y"] + box["height"] / 2 + random.uniform(-3, 3)
            await page.mouse.move(x, y, steps=random.randint(15, 30))
            await asyncio.sleep(_gauss_ms(150, 400))
        await element.click()
        await asyncio.sleep(_gauss_ms(400, 1200))

    async def scroll(self, page: "Page", *, total_px: int = 2000) -> None:
        scrolled = 0
        while scrolled < total_px:
            chunk = random.randint(120, 320)
            await page.mouse.wheel(0, chunk)
            scrolled += chunk
            await asyncio.sleep(_gauss_ms(400, 1100))
            if random.random() < 0.1:
                await page.mouse.wheel(0, -random.randint(40, 120))
                await asyncio.sleep(_gauss_ms(200, 600))

"""Keyword-reorder resume tailorer.

Reads resume_template.html, reorders the Technical Skills section so that
categories with the most JD keyword matches appear first, then renders a PDF
via Playwright. Content is never changed — only the category order.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Optional

from src.models import JDAnalysis
from src.utils.logger import logger

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "resume_template.html"
_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"

_BLOCK_START = "<!-- SKILLS_BLOCK_START -->"
_BLOCK_END = "<!-- SKILLS_BLOCK_END -->"

_ROW_RE = re.compile(
    r'<div class="skill-row"[^>]*data-category="([^"]*)"[^>]*data-skills="([^"]*)"[^>]*>(.*?)</div>',
    re.DOTALL,
)


def _score_category(skills_csv: str, keywords: list[str]) -> int:
    """Count how many JD keywords appear in this category's skill list."""
    skills_lower = {s.strip().lower() for s in skills_csv.split(",")}
    return sum(1 for kw in keywords if kw.lower() in skills_lower)


def _reorder_skills_block(html: str, keywords: list[str]) -> str:
    """Reorder skill-row divs inside the SKILLS_BLOCK markers by keyword match count."""
    start_idx = html.find(_BLOCK_START)
    end_idx = html.find(_BLOCK_END)
    if start_idx == -1 or end_idx == -1:
        logger.warning("SKILLS_BLOCK markers not found in template — using original order")
        return html

    block_start = start_idx + len(_BLOCK_START)
    block_content = html[block_start:end_idx]

    rows = _ROW_RE.findall(block_content)
    if not rows:
        return html

    # rows: list of (category, skills_csv, inner_html)
    # Rebuild full div strings by finding them in order
    div_strings: list[str] = _ROW_RE.findall(block_content)

    # Extract full div tags preserving exact original HTML
    full_divs: list[str] = re.findall(
        r'<div class="skill-row"[^>]*>.*?</div>', block_content, re.DOTALL
    )
    if not full_divs:
        return html

    # Score each div
    scored: list[tuple[int, str, str]] = []
    for div in full_divs:
        m = re.search(r'data-skills="([^"]*)"', div)
        skills_csv = m.group(1) if m else ""
        score = _score_category(skills_csv, keywords)
        cat_m = re.search(r'data-category="([^"]*)"', div)
        cat = cat_m.group(1) if cat_m else ""
        scored.append((score, cat, div))

    # Sort descending by score, stable (preserves original order for ties)
    scored.sort(key=lambda x: -x[0])

    new_block = "\n".join(f"  {div}" for _, _, div in scored)
    new_html = (
        html[:block_start]
        + "\n"
        + new_block
        + "\n"
        + html[end_idx:]
    )
    return new_html


def _safe_filename(text: str) -> str:
    return re.sub(r"[^\w\-]", "_", text).strip("_")[:60]


class ResumeTailor:
    """Generates a per-JD resume PDF by reordering Technical Skills only."""

    def __init__(self, template_path: Path = _TEMPLATE_PATH) -> None:
        self._template = template_path.read_text(encoding="utf-8")
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        company: str,
        role: str,
        analysis: Optional[JDAnalysis],
        static_fallback: Optional[Path] = None,
    ) -> Path:
        """Return path to a tailored PDF, or static_fallback on error."""
        try:
            return self._render(company, role, analysis)
        except Exception as exc:
            logger.warning(f"ResumeTailor failed ({exc}), using static resume")
            if static_fallback and static_fallback.exists():
                return static_fallback
            raise

    def _render(self, company: str, role: str, analysis: Optional[JDAnalysis]) -> Path:
        keywords = analysis.keywords_to_include if analysis else []
        html = self._template if not keywords else _reorder_skills_block(self._template, keywords)

        out_path = _OUTPUT_DIR / f"{_safe_filename(company)}_{_safe_filename(role)}.pdf"

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            with tempfile.NamedTemporaryFile(
                suffix=".html", delete=False, mode="w", encoding="utf-8"
            ) as tmp:
                tmp.write(html)
                tmp_path = Path(tmp.name)
            try:
                page.goto(tmp_path.as_uri())
                page.pdf(
                    path=str(out_path),
                    format="A4",
                    margin={"top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"},
                    print_background=True,
                )
            finally:
                tmp_path.unlink(missing_ok=True)
            browser.close()

        logger.info(f"Tailored resume → {out_path}")
        return out_path

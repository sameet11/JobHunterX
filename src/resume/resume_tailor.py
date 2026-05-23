"""ATS-optimized resume tailorer.

Applies four transformations to resume_template.html:
  1. Reorders Technical Skills categories by JD keyword match count.
  2. Reorders experience/project bullets within each BULLETS_START/END block
     so bullets containing JD keywords surface to the top.
  3. Generates a tailored professional summary via Gemini and injects it
     between SUMMARY_START / SUMMARY_END markers.
  4. Injects matched JD keywords as a Core Competencies section at KEYWORDS_INJECT.

Then renders to PDF via Playwright.
"""

from __future__ import annotations

import html as html_lib
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
_SUMMARY_START = "<!-- SUMMARY_START -->"
_SUMMARY_END = "<!-- SUMMARY_END -->"
_KEYWORDS_INJECT = "<!-- KEYWORDS_INJECT -->"
_BULLETS_START = "<!-- BULLETS_START -->"
_BULLETS_END = "<!-- BULLETS_END -->"


# ── 1. Skills category reordering ─────────────────────────────────────────

def _skills_csv(div: str) -> str:
    m = re.search(r'data-skills="([^"]*)"', div)
    return m.group(1) if m else ""


def _score_category(skills_csv: str, keywords: list[str]) -> int:
    skills_lower = {s.strip().lower() for s in skills_csv.split(",")}
    return sum(1 for kw in keywords if kw.lower() in skills_lower)


def _reorder_skills_block(html: str, keywords: list[str]) -> str:
    start_idx = html.find(_BLOCK_START)
    end_idx = html.find(_BLOCK_END)
    if start_idx == -1 or end_idx == -1:
        logger.warning("SKILLS_BLOCK markers not found — using original order")
        return html

    block_start = start_idx + len(_BLOCK_START)
    block_content = html[block_start:end_idx]

    full_divs = re.findall(
        r'<div class="skill-row"[^>]*>.*?</div>', block_content, re.DOTALL
    )
    if not full_divs:
        return html

    scored = sorted(full_divs, key=lambda d: -_score_category(_skills_csv(d), keywords))
    new_block = "\n".join(f"  {div}" for div in scored)
    return html[:block_start] + "\n" + new_block + "\n" + html[end_idx:]


# ── 2. Bullet reordering ───────────────────────────────────────────────────

def _score_bullet(li_html: str, keywords: list[str]) -> int:
    text = li_html.lower()
    return sum(1 for kw in keywords if kw.lower() in text)


def _reorder_bullets_blocks(html: str, keywords: list[str]) -> str:
    if not keywords:
        return html

    def reorder_block(match: re.Match) -> str:
        block = match.group(1)
        ul_match = re.search(r'(<ul[^>]*>)(.*?)(</ul>)', block, re.DOTALL)
        if not ul_match:
            return match.group(0)

        items = re.findall(r'<li[^>]*>(.*?)</li>', ul_match.group(2), re.DOTALL)
        if not items:
            return match.group(0)

        scored = sorted(items, key=lambda li: -_score_bullet(li, keywords))

        indent_m = re.search(r'\n(\s*)<li', ul_match.group(2))
        indent = indent_m.group(1) if indent_m else "    "

        new_items = "\n" + "\n".join(f"{indent}<li>{li}</li>" for li in scored) + "\n  "
        new_ul = ul_match.group(1) + new_items + ul_match.group(3)
        new_block = block[:ul_match.start()] + new_ul + block[ul_match.end():]
        return _BULLETS_START + new_block + _BULLETS_END

    return re.sub(
        re.escape(_BULLETS_START) + r"(.*?)" + re.escape(_BULLETS_END),
        reorder_block,
        html,
        flags=re.DOTALL,
    )


# ── 3. Gemini summary tailoring ────────────────────────────────────────────

def _extract_summary(html: str) -> str:
    start_idx = html.find(_SUMMARY_START)
    end_idx = html.find(_SUMMARY_END)
    if start_idx == -1 or end_idx == -1:
        return ""
    raw = html[start_idx + len(_SUMMARY_START):end_idx]
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html_lib.unescape(text)
    return " ".join(text.split())


def _generate_summary(original: str, company: str, role: str, keywords: list[str]) -> str:
    try:
        from src.utils.gemini_client import get_model, text_generation_config
        model = get_model(
            system_instruction=(
                "You are a professional resume writer. Rewrite the summary to be ATS-optimized "
                "for a specific role. Rules: (1) 2-3 sentences max, (2) include 3-5 of the provided "
                "keywords naturally, (3) keep all quantified achievements from the original, "
                "(4) do NOT add fake skills or experience, (5) plain text only, no markdown or HTML."
            )
        )
        top_kw = ", ".join(keywords[:8])
        prompt = (
            f"Target role: {role} at {company}\n"
            f"Key JD keywords: {top_kw}\n\n"
            f"Original summary:\n{original}\n\n"
            f"Rewrite:"
        )
        response = model.generate_content(prompt, generation_config=text_generation_config(max_tokens=160))
        text = response.text.strip()
        if text:
            logger.info(f"Gemini tailored summary for {company} — {role}")
            return text
    except Exception as exc:
        logger.warning(f"Gemini summary generation failed ({exc}) — keeping original")
    return original


def _inject_summary(html: str, summary: str) -> str:
    start_idx = html.find(_SUMMARY_START)
    end_idx = html.find(_SUMMARY_END)
    if start_idx == -1 or end_idx == -1:
        return html
    escaped = html_lib.escape(summary)
    return (
        html[:start_idx + len(_SUMMARY_START)]
        + "\n  " + escaped + "\n"
        + html[end_idx:]
    )


# ── 4. Core Competencies injection ────────────────────────────────────────

def _inject_core_competencies(html: str, keywords: list[str]) -> str:
    if not keywords or _KEYWORDS_INJECT not in html:
        return html
    kw_text = " &middot; ".join(html_lib.escape(kw) for kw in keywords[:12])
    section = (
        f'<div class="section-title">Core Competencies</div>\n'
        f'<div class="skills-block"><div>{kw_text}</div></div>\n'
    )
    return html.replace(_KEYWORDS_INJECT, section, 1)


# ── Helpers ────────────────────────────────────────────────────────────────

def _safe_filename(text: str) -> str:
    return re.sub(r"[^\w\-]", "_", text).strip("_")[:60]


# ── Main class ─────────────────────────────────────────────────────────────

class ResumeTailor:

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
        try:
            return self._render(company, role, analysis)
        except Exception as exc:
            logger.warning(f"ResumeTailor failed ({exc}), using static resume")
            if static_fallback and static_fallback.exists():
                return static_fallback
            raise

    def _render(self, company: str, role: str, analysis: Optional[JDAnalysis]) -> Path:
        keywords = analysis.keywords_to_include if analysis else []
        html = self._template

        if keywords:
            html = _reorder_skills_block(html, keywords)
            html = _reorder_bullets_blocks(html, keywords)

        if keywords and _SUMMARY_START in html:
            original = _extract_summary(html)
            tailored = _generate_summary(original, company, role, keywords)
            html = _inject_summary(html, tailored)

        if keywords:
            html = _inject_core_competencies(html, keywords)

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

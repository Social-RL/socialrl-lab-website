#!/usr/bin/env python3
"""
Parse \PaperEntry commands from cv.tex and compare against publications.html.

Uses the Claude API for fuzzy title matching so that minor wording differences
(e.g. "Real-Time, Synchronous" vs "Real-Time") don't cause false positives.

Usage:
    python parse_cv.py [--cv path/to/cv.tex] [--pub path/to/publications.html]

Requires:
    pip install anthropic

\PaperEntry argument order: {authors}{title}{venue}{location}{year}{link}
"""

import re
import json
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Paper:
    authors: str
    title: str
    venue: str
    location: str
    year: int
    link: str

    @property
    def is_preprint(self) -> bool:
        return "(in submission)" in self.venue.lower() or self.venue.strip().lower() == "preprint"

    @property
    def published_venue(self) -> str:
        """Venue string with LaTeX bold markup stripped."""
        v = re.sub(r"\\textbf\{([^}]*)\}", r"\1", self.venue)
        v = re.sub(r"\s+", " ", v).strip()
        return v


# ---------------------------------------------------------------------------
# LaTeX parsing
# ---------------------------------------------------------------------------

def extract_braced(text: str, start: int) -> tuple[str, int]:
    """
    Extract the content of the balanced-brace group starting at `start`
    (which must point at the opening '{').
    Returns (content, index_after_closing_brace).
    """
    assert text[start] == "{", f"Expected '{{' at {start}, got {text[start]!r}"
    depth = 0
    i = start
    buf: list[str] = []
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            buf.append(ch)
            buf.append(text[i + 1])
            i += 2
            continue
        if ch == "{":
            depth += 1
            if depth > 1:
                buf.append(ch)
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return "".join(buf), i + 1
            else:
                buf.append(ch)
        else:
            buf.append(ch)
        i += 1
    raise ValueError(f"Unmatched brace starting at {start}")


def parse_paper_entries(cv_text: str, min_year: int = 2024) -> list[Paper]:
    papers = []
    for m in re.finditer(r"\\PaperEntry\s*\{", cv_text):
        start = m.end() - 1
        try:
            authors, pos = extract_braced(cv_text, start)
            for _ in range(5):  # title, venue, location, year, link
                while pos < len(cv_text) and cv_text[pos] in " \t\n\r":
                    pos += 1
                if pos >= len(cv_text) or cv_text[pos] != "{":
                    break
                if _ == 0:
                    title, pos = extract_braced(cv_text, pos)
                elif _ == 1:
                    venue, pos = extract_braced(cv_text, pos)
                elif _ == 2:
                    location, pos = extract_braced(cv_text, pos)
                elif _ == 3:
                    year_str, pos = extract_braced(cv_text, pos)
                elif _ == 4:
                    link, pos = extract_braced(cv_text, pos)
        except (AssertionError, ValueError, IndexError):
            continue

        if authors.startswith("#"):  # skip \newcommand definition
            continue

        link = link.strip()
        if not link:
            continue

        try:
            year = int(year_str.strip())
        except ValueError:
            continue

        if year < min_year:
            continue

        papers.append(Paper(
            authors=authors.strip(),
            title=title.strip(),
            venue=venue.strip(),
            location=location.strip(),
            year=year,
            link=link,
        ))

    return papers


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def normalise_title(t: str) -> str:
    t = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", t)
    t = re.sub(r"\\[^a-zA-Z]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def extract_site_titles(pub_html: str) -> list[str]:
    """Return all raw (HTML-stripped) titles from publications.html."""
    titles = []
    for m in re.finditer(r'class="pubtitle"[^>]*>\s*(.*?)\s*</div>', pub_html, re.DOTALL):
        raw = re.sub(r"<[^>]+>", "", m.group(1))
        titles.append(raw.strip())
    return titles


def extract_preprint_titles(pub_html: str) -> list[str]:
    """Return titles that appear inside the Preprints section."""
    section_match = re.search(
        r'<h2>\s*Preprints\s*</h2>(.*?)<h2>',
        pub_html,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return []
    section = section_match.group(1)
    titles = []
    for m in re.finditer(r'class="pubtitle"[^>]*>\s*(.*?)\s*</div>', section, re.DOTALL):
        raw = re.sub(r"<[^>]+>", "", m.group(1))
        titles.append(raw.strip())
    return titles


# ---------------------------------------------------------------------------
# LLM-based fuzzy title matching
# ---------------------------------------------------------------------------

def llm_match_titles(
    cv_papers: list[Paper],
    site_titles: list[str],
    client: anthropic.Anthropic,
) -> dict[str, Optional[str]]:
    """
    For each CV paper title, ask Claude whether any site title refers to the
    same paper.  Returns a dict mapping cv_paper.title → matching site title
    (or None if no match found).

    Batches all queries into a single API call to minimise latency/cost.
    """
    cv_titles = [p.title for p in cv_papers]

    prompt = (
        "You are helping maintain an academic lab website. "
        "I have a list of paper titles from a CV (source) and a list of titles "
        "already on the website (site). Titles may differ slightly — e.g. one "
        "version may include a subtitle, use slightly different wording, or have "
        "minor formatting differences — but still refer to the same paper.\n\n"
        "For each CV title, find the BEST matching site title (if any). "
        "Two titles match only if they clearly describe the SAME paper. "
        "Papers that share a word or theme but have different titles are NOT a match "
        "(e.g. 'ReaLJam: Real-Time Human-AI Music Jamming...' and "
        "'Adaptive Accompaniment with ReaLchords' are two completely distinct papers). "
        "If no site title is a good match, return null.\n\n"
        f"CV titles (JSON array, 0-indexed):\n{json.dumps(cv_titles, indent=2)}\n\n"
        f"Site titles (JSON array):\n{json.dumps(site_titles, indent=2)}\n\n"
        "Return ONLY a JSON object mapping each CV title (exactly as given) to "
        "the matching site title string (exactly as given in the site list) or "
        "null if there is no match. No explanation, just JSON."
    )

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: no matches
        print(f"  [warn] LLM returned unparseable JSON, falling back to exact matching")
        result = {}

    return result


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def clean_latex(s: str) -> str:
    s = re.sub(r"\\underline\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\[^a-zA-Z\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def generate_html_entry(paper: Paper) -> str:
    clean_authors = clean_latex(paper.authors)
    clean_title = clean_latex(paper.title)

    venue_display = paper.published_venue
    venue_display = re.sub(
        r"(Best Paper[^,<]*|Oral[^,<]*top[^)]*\)|Spotlight[^,<]*top[^)]*\)|Outstanding Paper[^,<]*)",
        r'<span style="font-weight: bold;">\1</span>',
        venue_display,
    )

    venue_line = ""
    if not paper.is_preprint:
        venue_line = (
            f'\n                <div class="pubinfo">\n'
            f'                  {venue_display} {paper.year}\n'
            f'                </div>'
        )

    return (
        f'              <div class="robotics rl pubitem">\n'
        f'                <div class="pubtitle">\n'
        f'                  {clean_title}\n'
        f'                </div>\n'
        f'                <div class="pubauthors">\n'
        f'                  {clean_authors}\n'
        f'                </div>{venue_line}\n'
        f'                <div class="publinks">\n'
        f'                  <a href="{paper.link}"><i class="fa fa-file-pdf-o"></i>Paper</a>&nbsp;&nbsp;\n'
        f'                </div>\n'
        f'              </div>'
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cv",
        default=str(Path.home() / "Downloads/CV/cv.tex"),
        help="Path to cv.tex",
    )
    parser.add_argument(
        "--pub",
        default=str(Path(__file__).parent.parent / "publications.html"),
        help="Path to publications.html",
    )
    args = parser.parse_args()

    cv_text = Path(args.cv).read_text(encoding="utf-8", errors="replace")
    pub_html = Path(args.pub).read_text(encoding="utf-8", errors="replace")

    cv_papers = parse_paper_entries(cv_text)
    site_titles = extract_site_titles(pub_html)
    preprint_titles_on_site = extract_preprint_titles(pub_html)

    print("Querying Claude for fuzzy title matching…")
    client = anthropic.Anthropic()
    title_matches = llm_match_titles(cv_papers, site_titles, client)

    # Reverse map: site title → cv title (for detecting preprint→year moves)
    site_preprint_set = {normalise_title(t) for t in preprint_titles_on_site}

    missing: list[Paper] = []
    needs_move: list[Paper] = []

    for p in cv_papers:
        matched_site_title = title_matches.get(p.title)
        on_site = matched_site_title is not None
        if not on_site:
            missing.append(p)
        elif not p.is_preprint and normalise_title(matched_site_title) in site_preprint_set:
            needs_move.append(p)

    # ---- Report ----------------------------------------------------------------
    print("\n" + "=" * 70)
    print("CV IMPORT REPORT")
    print("=" * 70)

    if needs_move:
        print(f"\n🔄  MOVE FROM PREPRINTS → year section ({len(needs_move)} paper(s)):\n")
        for p in needs_move:
            matched = title_matches.get(p.title, "(unknown)")
            print(f"  [{p.year}] CV title   : {clean_latex(p.title)}")
            print(f"         Site title : {matched}")
            print(f"         Venue      : {p.published_venue}")
            print(f"         Link       : {p.link}")
            print()

    if missing:
        preprint_missing = [p for p in missing if p.is_preprint]
        published_missing = [p for p in missing if not p.is_preprint]

        if preprint_missing:
            print(f"\n➕  MISSING FROM PREPRINTS ({len(preprint_missing)} paper(s)):\n")
            for p in preprint_missing:
                print(f"  {clean_latex(p.title)}")
                print(f"         Venue : {p.published_venue}")
                print(f"         Link  : {p.link}")
                print()
                print("  Suggested HTML:")
                print(generate_html_entry(p))
                print()

        if published_missing:
            by_year: dict[int, list[Paper]] = {}
            for p in published_missing:
                by_year.setdefault(p.year, []).append(p)
            for year in sorted(by_year, reverse=True):
                print(f"\n➕  MISSING FROM {year} ({len(by_year[year])} paper(s)):\n")
                for p in by_year[year]:
                    print(f"  {clean_latex(p.title)}")
                    print(f"         Venue : {p.published_venue}")
                    print(f"         Link  : {p.link}")
                    print()
                    print("  Suggested HTML:")
                    print(generate_html_entry(p))
                    print()

    if not missing and not needs_move:
        print("\n✅  Publications page appears up to date with CV (2024+).")

    print("=" * 70)


if __name__ == "__main__":
    main()

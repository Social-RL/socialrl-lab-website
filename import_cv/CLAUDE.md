# CLAUDE.md

## Author names on publications.html

Never type, retype, autocomplete, or "correct" an author's name from memory.
Author names (especially first/given names) must be copied character-for-character
from an authoritative source — `import_cv/cv.tex` (the `\PaperEntry{authors}{...}`
field) or text the user pastes directly in chat. If neither is available for a
given paper, leave the name as-is and flag it to the user instead of guessing.

This rule exists because names were previously hallucinated when porting papers
from the CV to the site (e.g. "Ricky Cheng" instead of "Ryan Cheng", "Haeone Nam"
instead of "Hyunji Nam") — plausible-sounding but wrong, and easy to miss without
a side-by-side diff against the source. `import_cv/parse_cv.py` already extracts
`paper.authors` verbatim from `cv.tex` for this reason — when copying its
"Suggested HTML" output into `publications.html`, paste it verbatim rather than
re-typing it.

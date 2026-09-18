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

To get correct first/given names for an author list, fetch the paper's arXiv
abstract page and read the byline from there — don't rely on the CV's author
string alone (it may abbreviate to initials) and don't guess.

## Importing new publications from the CV

- Confirm with the user before adding a new publication to publications.html,
  and before modifying an existing entry. Propose the change and wait for
  their go-ahead — don't apply it unilaterally, even if it looks like an
  obvious fix.
- A CV entry whose venue field says "(in submission)" (or similar) is a
  preprint. Don't add it to the website unless the CV entry also includes a
  link to the paper. No link → skip it (don't stub in a placeholder link).
- A "Google DeepMind Technical Report" (or similar corporate technical
  report) is not a preprint-in-submission — it will never move to a
  peer-reviewed venue. File it under the year heading it was published in,
  not under Preprints.

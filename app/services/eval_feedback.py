"""eval_feedback — turn recent F/S/B scoring into a critic-prompt addendum.

Scope: a small reader on the `eval_card_scores` table. Surfaces failure
patterns from the last N weeks (excluding the week being synthesized)
so the synthesis critic prompt can list them as "past concerns" — and
so `/eval` can render the same block for transparency.

Filter:
  - `fail` and `concern` scores count (fail weighted higher when sorted)
  - only patterns where the same (card, dim) shows up >= MIN_OCCURRENCES
    times in the window — single fails are noise
  - notes are included when present, tagged with their week_id
  - `na` and `pass` scores ignored

Returns an empty list / empty string when nothing qualifies; callers
short-circuit the injection.
"""
from __future__ import annotations

from collections import defaultdict

from sqlmodel import Session, select

from app.db.models import EvalCardScore


_DIM_ATTRS = [("F", "f_score"), ("S", "s_score"), ("B", "b_score")]
_DIM_NAMES = {"F": "Factuality", "S": "Signal", "B": "Brevity"}
LOOKBACK_DEFAULT = 4
MIN_OCCURRENCES = 2


def _iso_week_lookback(current_week_id: str, lookback: int) -> list[str]:
    """Return the `lookback` most-recent ISO week ids strictly BEFORE
    `current_week_id`. Format: 'YYYY-Www'.

    Edge case — W53 years (about 1 in 6): we treat each year as 52 weeks
    on rollover. That loses at most one week of lookback at year-bounds
    and is acceptable for a feedback heuristic.
    """
    try:
        year_str, w_str = current_week_id.split("-W")
        year = int(year_str)
        week = int(w_str)
    except (ValueError, IndexError):
        return []
    out: list[str] = []
    y, w = year, week
    for _ in range(lookback):
        w -= 1
        if w < 1:
            y -= 1
            w = 52
        out.append(f"{y}-W{w:02d}")
    return out


def gather_recent_failures(
    session: Session,
    current_week_id: str,
    lookback_weeks: int = LOOKBACK_DEFAULT,
    min_occurrences: int = MIN_OCCURRENCES,
) -> list[dict]:
    """Surface recurring (card, dim) failure patterns from recent weeks.

    Each entry: {card, dim, dim_name, fails, concerns, notes: [(week_id, text)]}.
    Sorted by severity (fails*2 + concerns) DESC.
    """
    window = _iso_week_lookback(current_week_id, lookback_weeks)
    if not window:
        return []
    rows = session.exec(
        select(EvalCardScore).where(EvalCardScore.week_id.in_(window))
    ).all()
    if not rows:
        return []

    by_pair: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"fails": 0, "concerns": 0, "notes": []}
    )
    for r in rows:
        note_text = (r.note or "").strip()
        for dim, attr in _DIM_ATTRS:
            score = getattr(r, attr)
            if score == "fail":
                by_pair[(r.card, dim)]["fails"] += 1
            elif score == "concern":
                by_pair[(r.card, dim)]["concerns"] += 1
            else:
                continue
            # Attach the note to every dim that failed/concerned for this row,
            # so a single multi-dim failure with one note surfaces under all.
            if note_text:
                pair_notes = by_pair[(r.card, dim)]["notes"]
                if (r.week_id, note_text) not in pair_notes:
                    pair_notes.append((r.week_id, note_text))

    out: list[dict] = []
    for (card, dim), agg in by_pair.items():
        total = agg["fails"] + agg["concerns"]
        if total < min_occurrences:
            continue
        out.append({
            "card": card,
            "dim": dim,
            "dim_name": _DIM_NAMES.get(dim, dim),
            "fails": agg["fails"],
            "concerns": agg["concerns"],
            "notes": sorted(agg["notes"], reverse=True),  # newest week first
        })
    out.sort(key=lambda x: (x["fails"] * 2 + x["concerns"]), reverse=True)
    return out


def format_critic_block(failures: list[dict]) -> str:
    """Format the failures list as a plain-text block for the critic prompt.

    Returns "" when no failures — callers should not prepend anything.
    """
    if not failures:
        return ""
    lines: list[str] = []
    lines.append("=== PAST HUMAN CONCERNS (recurring patterns from recent reviews) ===")
    lines.append(
        "The following failure modes came up at least twice in the last 4 weeks "
        "of human review. Apply them as additional quality checks to THIS week's "
        "revision. Do NOT mention these concerns in your output — silently fix."
    )
    lines.append("")
    for f in failures:
        sev_parts = []
        if f["fails"]:
            sev_parts.append(f"{f['fails']} fail" + ("s" if f["fails"] != 1 else ""))
        if f["concerns"]:
            sev_parts.append(f"{f['concerns']} concern" + ("s" if f["concerns"] != 1 else ""))
        sev = ", ".join(sev_parts)
        lines.append(f"- {f['card']} / {f['dim_name']} ({sev})")
        for week_id, note in f["notes"][:3]:  # up to 3 examples per pattern
            lines.append(f"    {week_id}: \"{note}\"")
    lines.append("")
    return "\n".join(lines)

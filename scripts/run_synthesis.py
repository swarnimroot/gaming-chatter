"""Standalone runner for the Phase 3c.4 weekly synthesis pass.

Usage:
    python scripts/run_synthesis.py 2026-W19
    python scripts/run_synthesis.py 2026-W19 --force      # bypass cache
    python scripts/run_synthesis.py 2026-W19 --dry-run    # print input prompt only, no API call

Synthesis runs Opus 4.7 twice (synthesis + critic). Estimated spend per run:
~$0.30 synthesis + ~$0.05 critic = ~$0.35. Persists to weekly_reports.synthesis_json
and overwrites exec_summary_text with the synthesis paragraph.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows cp1252 stdout can't encode non-Latin characters that appear in
# synthesis output (e.g., Japanese names with macrons). Reconfigure to utf-8
# so the post-run print loop doesn't crash AFTER successful persistence.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)

from sqlmodel import Session  # noqa: E402

from app.db.init import init_db  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.services import synthesis  # noqa: E402

log = logging.getLogger("synthesis_runner")

# Run idempotent migrations up-front so the standalone script doesn't depend on
# the FastAPI lifespan hook to have fired against the same DB file.
init_db()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("week_id", help="ISO week id, e.g. 2026-W19")
    parser.add_argument("--force", action="store_true",
                        help="Bypass synthesis cache and re-run even if a row exists.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the assembled input prompt and exit without calling Opus.")
    args = parser.parse_args()

    with Session(engine) as session:
        if args.dry_run:
            log.info("=== dry-run: assembling input for week %s ===", args.week_id)
            data = synthesis._build_input_dict(session, args.week_id)
            text = synthesis._format_input_for_prompt(data)
            sys.stdout.write("\n========= INPUT PROMPT =========\n\n")
            sys.stdout.write(text)
            sys.stdout.write("\n\n========= END =========\n")
            sys.stdout.write(
                f"\nINPUT CHARS: {len(text):,}  "
                f"(~{len(text)//4:,} tokens at 4 chars/tok)\n"
                f"CLUSTERS: {len(data['clusters'])}, "
                f"REDDIT_CLUSTERS: {len(data['reddit_clusters'])}, "
                f"TOP_GAMES: {len(data['top_games'])}, "
                f"UPCOMING: {len(data['upcoming_releases'])}\n"
            )
            return 0

        t0 = time.time()
        log.info("=== synthesize_week start (week_id=%s, force=%s) ===", args.week_id, args.force)
        result = synthesis.synthesize_week(session, args.week_id, force=args.force)
        elapsed = time.time() - t0
        log.info(
            "synthesize_week done in %.1fs (from_cache=%s, model=%s)",
            elapsed, result["from_cache"], result["model"],
        )

        synth = result["synthesis"]
        log.info(
            "result: biggest=%d, hottest_reasons=%d, MM=%d, "
            "CS(narr=%d heated=%d celebrating=%d), risks=%d, "
            "esports=%d, drama=%d, release_notes=%d, watch=%d, "
            "exec_summary=%d chars",
            len(synth["biggest"]),
            len(synth["hottest_reasons"]),
            len(synth["market_momentum"]),
            len(synth["community_sentiment"]["narrative"]),
            len(synth["community_sentiment"]["heated_about"]),
            len(synth["community_sentiment"]["celebrating"]),
            len(synth["risks"]),
            len(synth["esports"]),
            len(synth["drama"]),
            len(synth["release_notes"]),
            len(synth["watch"]),
            len(synth["exec_summary_paragraph"]),
        )

        # Pretty-print the biggest stories + exec-summary so the user can eyeball quality
        sys.stdout.write("\n========= EXEC SUMMARY =========\n\n")
        sys.stdout.write(synth["exec_summary_paragraph"])
        sys.stdout.write("\n\n========= BIGGEST =========\n\n")
        for i, b in enumerate(synth["biggest"], 1):
            sys.stdout.write(f"{i}. [{b['cluster_id']}] {b['title']}\n   {b['dek']}\n\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

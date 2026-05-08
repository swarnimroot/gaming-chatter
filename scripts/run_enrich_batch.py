"""Standalone runner for the full enrichment + embedding batch.

Runs enrich_pending() then embed_pending(), each producing a RunLog row.
Output is logged so we can tail progress while the batch runs.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)

from app.services.enrich import embed_pending, enrich_pending  # noqa: E402

log = logging.getLogger("batch")


def main() -> int:
    t0 = time.time()
    log.info("=== enrich_pending start ===")
    enrich_totals = enrich_pending()
    log.info("enrich_pending done in %.1fs: %s", time.time() - t0, enrich_totals)

    t1 = time.time()
    log.info("=== embed_pending start ===")
    embed_totals = embed_pending()
    log.info("embed_pending done in %.1fs: %s", time.time() - t1, embed_totals)

    log.info("=== batch complete; total %.1fs ===", time.time() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

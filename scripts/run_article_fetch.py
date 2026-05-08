"""Phase 2.5 standalone runner.

Chains three steps so the whole remediation pass runs unattended:
  1. fetch_skipped_bodies()              — re-fetch article bodies for skipped rows
  2. enrich_pending(retry_failed=True)   — re-enrich every non-ok row
  3. embed_pending()                     — top-up embeddings for new ok rows

Each step writes its own RunLog row.
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

from app.services.article_fetch import fetch_skipped_bodies  # noqa: E402
from app.services.enrich import embed_pending, enrich_pending  # noqa: E402

log = logging.getLogger("batch")


def main() -> int:
    t0 = time.time()
    log.info("=== fetch_skipped_bodies start ===")
    fetch_totals = fetch_skipped_bodies()
    log.info("fetch_skipped_bodies done in %.1fs: %s", time.time() - t0, fetch_totals)

    t1 = time.time()
    log.info("=== enrich_pending(retry_failed=True) start ===")
    enrich_totals = enrich_pending(retry_failed=True)
    log.info("enrich_pending done in %.1fs: %s", time.time() - t1, enrich_totals)

    t2 = time.time()
    log.info("=== embed_pending start ===")
    embed_totals = embed_pending()
    log.info("embed_pending done in %.1fs: %s", time.time() - t2, embed_totals)

    log.info("=== batch complete; total %.1fs ===", time.time() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

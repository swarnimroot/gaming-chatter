from datetime import datetime
from typing import Optional

from sqlalchemy import Column, LargeBinary, Text
from sqlmodel import Field, SQLModel


class Source(SQLModel, table=True):
    __tablename__ = "sources"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    type: str  # rss | youtube
    url_or_handle: str
    enabled: bool = True
    last_fetched_at: Optional[datetime] = None
    last_error: Optional[str] = None
    error_count: int = 0


class RawItem(SQLModel, table=True):
    __tablename__ = "raw_items"
    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    external_id: str = Field(index=True)
    raw_payload: str = Field(sa_column=Column(Text))
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class Item(SQLModel, table=True):
    __tablename__ = "items"
    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    raw_item_id: Optional[int] = Field(default=None, foreign_key="raw_items.id")
    title: str
    url: str = Field(index=True)
    body_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    author: Optional[str] = None
    published_at: Optional[datetime] = Field(default=None, index=True)
    score: Optional[int] = None
    comment_count: Optional[int] = None
    fingerprint: str = Field(index=True)


class Enrichment(SQLModel, table=True):
    __tablename__ = "enrichments"
    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="items.id", unique=True, index=True)
    tldr: Optional[str] = Field(default=None, sa_column=Column(Text))
    entities: Optional[str] = Field(default=None, sa_column=Column(Text))
    category: Optional[str] = None
    sentiment_score: Optional[float] = None
    sentiment_summary: Optional[str] = None
    embedding: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary))
    status: str = Field(default="ok", index=True)  # ok | failed
    error: Optional[str] = Field(default=None, sa_column=Column(Text))
    genres: Optional[str] = Field(default=None, sa_column=Column(Text))
    platforms: Optional[str] = Field(default=None, sa_column=Column(Text))
    event: Optional[str] = None
    region_focus: Optional[str] = None  # comma-separated subset of {americas, europe, asia} or NULL — Phase 3c.15
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Game(SQLModel, table=True):
    __tablename__ = "games"
    name: str = Field(primary_key=True)
    lifecycle: Optional[str] = None         # 'existing' | 'upcoming' | NULL
    live_service: Optional[bool] = None     # SQLite stores as 0/1
    release_date: Optional[str] = None      # ISO date 'YYYY-MM-DD', 'YYYY-MM', 'YYYY', or NULL when unknown / TBA


class GameRelease(SQLModel, table=True):
    """Authoritative game release dates from external sources (Phase 3c.18).

    Multi-source — current sources: 'pcgamer' (3c.18) + 'ign' (3c.24).
    Composite PK (game_name_lc, source) so both sources can hold rows for the
    same game; resolver picks pcgamer over ign on conflict.

    `games.release_date` and `games.lifecycle` remain as a synced cache —
    sync_games_dim writes derived values here after each refresh so existing
    consumers (Release Radar, top_games_for_week, etc.) keep working unchanged.
    """
    __tablename__ = "game_releases"
    game_name_lc: str = Field(primary_key=True)             # lookup key (lowercased)
    source: str = Field(primary_key=True)                   # 'pcgamer' | 'ign'
    game_name: str                                          # display casing
    release_date: Optional[str] = None                      # locked formats from reports.is_future_or_unknown
    raw_label: Optional[str] = None                         # original phrasing from source (e.g. "Q3 2026")
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Cluster(SQLModel, table=True):
    __tablename__ = "clusters"
    id: Optional[int] = Field(default=None, primary_key=True)
    week_id: str = Field(index=True)
    label: str
    centroid: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary))
    member_item_ids: str = Field(sa_column=Column(Text))
    member_count: int
    source_count: Optional[int] = None
    latest_published_at: Optional[datetime] = None
    score: Optional[float] = Field(default=None, index=True)


class WeeklyReport(SQLModel, table=True):
    __tablename__ = "weekly_reports"
    id: Optional[int] = Field(default=None, primary_key=True)
    week_start: datetime = Field(index=True)
    week_end: datetime
    markdown_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    html_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    exec_summary_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    exec_summary_model: Optional[str] = None
    exec_summary_generated_at: Optional[datetime] = None
    synthesis_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    synthesis_model: Optional[str] = None
    synthesis_generated_at: Optional[datetime] = None
    # Phase 3c.35 — precomputed `_build_week_payload(region="")` cache.
    # Populated by the synthesis hook and by scripts/rebuild_dashboard_payloads.py.
    # `/reports` reads this on hit and applies the cheap region filter in-memory,
    # short-circuiting the ~2.5s live aggregation.
    dashboard_payload_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    generated_at: Optional[datetime] = None
    status: str = "pending"


class RunLog(SQLModel, table=True):
    __tablename__ = "run_log"
    id: Optional[int] = Field(default=None, primary_key=True)
    job_type: str = Field(index=True)
    source_id: Optional[int] = Field(default=None, foreign_key="sources.id")
    started_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    completed_at: Optional[datetime] = None
    status: str
    items_processed: int = 0
    error: Optional[str] = None


class EvalCardScore(SQLModel, table=True):
    """In-app synthesis-quality scores per (week, card). Phase 3c.25.

    Three dimensions stored as separate columns so the row is the unit a
    human fills in while reading the report: F (Factuality), S (Signal),
    B (Brevity). Composite PK (week_id, card) — one row per card-eval.
    """
    __tablename__ = "eval_card_scores"
    week_id: str = Field(primary_key=True)           # ISO week "2026-W20"
    card: str = Field(primary_key=True)              # "biggest" | "watch" | "exec_paragraph" | ...
    f_score: Optional[str] = None                    # "pass" | "concern" | "fail" | "na" | NULL
    s_score: Optional[str] = None
    b_score: Optional[str] = None
    note: Optional[str] = Field(default=None, sa_column=Column(Text))
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EvalMeta(SQLModel, table=True):
    """Per-week eval metadata — currently just the free-text 'Missing' field.
    Phase 3c.25."""
    __tablename__ = "eval_meta"
    week_id: str = Field(primary_key=True)
    missing: Optional[str] = Field(default=None, sa_column=Column(Text))
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class JobRun(SQLModel, table=True):
    """Higher-level orchestrator run log (Phase 4 automation).

    Distinct from the granular per-step `RunLog`/`run_log` table that
    ingest/enrich/embed/cluster/article_fetch already populate. A `JobRun`
    row tracks one orchestrator invocation (`daily_pipeline`,
    `weekly_extension`, `release_refresh`, or a granular manual trigger).
    Per-step details for the daily pipeline are encoded in `details_json`
    rather than as separate rows so the /runs UI can show one parent row
    per scheduled invocation.
    """
    __tablename__ = "job_runs"
    id: Optional[int] = Field(default=None, primary_key=True)
    job_name: str = Field(index=True)           # 'daily_pipeline' | 'weekly_extension' | 'release_refresh' | granular job name
    started_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    finished_at: Optional[datetime] = None
    status: str = Field(default="running", index=True)  # 'running' | 'ok' | 'degraded' | 'failed' | 'skipped'
    duration_seconds: Optional[float] = None
    message: Optional[str] = Field(default=None, sa_column=Column(Text))    # short summary or error
    details_json: Optional[str] = Field(default=None, sa_column=Column(Text))  # per-step counts
    triggered_by: str = Field(default="scheduler")      # 'scheduler' | 'manual' | 'startup_catchup'

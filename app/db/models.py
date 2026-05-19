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

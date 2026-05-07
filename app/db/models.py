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
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Cluster(SQLModel, table=True):
    __tablename__ = "clusters"
    id: Optional[int] = Field(default=None, primary_key=True)
    week_id: str = Field(index=True)
    label: str
    centroid: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary))
    member_item_ids: str = Field(sa_column=Column(Text))
    member_count: int


class WeeklyReport(SQLModel, table=True):
    __tablename__ = "weekly_reports"
    id: Optional[int] = Field(default=None, primary_key=True)
    week_start: datetime = Field(index=True)
    week_end: datetime
    markdown_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    html_content: Optional[str] = Field(default=None, sa_column=Column(Text))
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

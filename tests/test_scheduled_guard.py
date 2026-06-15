"""Unit tests for jobs.run_daily_pipeline_scheduled — the dedup guard that
keeps the in-process APScheduler cron and the Windows Task Scheduler poke
from double-running the same night's daily."""

from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.services.jobs as jobs
from app.db.models import JobRun


@pytest.fixture()
def mem_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(jobs, "engine", engine)
    return engine


@pytest.fixture()
def pipeline_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        jobs, "run_daily_pipeline",
        lambda triggered_by="scheduler": calls.append(triggered_by) or {"stub": True},
    )
    return calls


def _add_run(engine, status, hours_ago, job_name="daily_pipeline"):
    with Session(engine) as session:
        session.add(JobRun(
            job_name=job_name,
            started_at=datetime.utcnow() - timedelta(hours=hours_ago),
            status=status,
            triggered_by="manual",
        ))
        session.commit()


def test_runs_when_no_prior_daily(mem_engine, pipeline_calls):
    assert jobs.run_daily_pipeline_scheduled(triggered_by="schtask") == {"stub": True}
    assert pipeline_calls == ["schtask"]


@pytest.mark.parametrize("status", ["ok", "degraded", "running"])
def test_skips_when_recent_daily(mem_engine, pipeline_calls, status):
    _add_run(mem_engine, status, hours_ago=2)
    assert jobs.run_daily_pipeline_scheduled() is None
    assert pipeline_calls == []


def test_runs_when_last_daily_outside_window(mem_engine, pipeline_calls):
    _add_run(mem_engine, "ok", hours_ago=13)
    assert jobs.run_daily_pipeline_scheduled() == {"stub": True}
    assert pipeline_calls == ["scheduler"]


def test_recent_failed_does_not_block_retry(mem_engine, pipeline_calls):
    _add_run(mem_engine, "failed", hours_ago=1)
    assert jobs.run_daily_pipeline_scheduled() == {"stub": True}


def test_skipped_rows_do_not_mask_or_block(mem_engine, pipeline_calls):
    # A lock-contention 'skipped' row newer than an ok row must not block,
    # and must not mask a recent ok row either.
    _add_run(mem_engine, "ok", hours_ago=2)
    _add_run(mem_engine, "skipped", hours_ago=1)
    assert jobs.run_daily_pipeline_scheduled() is None  # the ok row still guards
    _add_run(mem_engine, "skipped", hours_ago=0)
    assert pipeline_calls == []


def test_other_job_names_ignored(mem_engine, pipeline_calls):
    _add_run(mem_engine, "ok", hours_ago=1, job_name="enrich_only")
    assert jobs.run_daily_pipeline_scheduled() == {"stub": True}

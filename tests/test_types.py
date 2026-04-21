from __future__ import annotations

import pytest
from pydantic import ValidationError

from kore.llm.types import ResearchReport, Source


def test_source_roundtrip():
    src = Source(url="https://example.com", title="Example", snippet="snippet")
    dumped = src.model_dump()
    assert dumped == {
        "url": "https://example.com",
        "title": "Example",
        "snippet": "snippet",
    }


def test_research_report_validates_fields():
    report = ResearchReport(
        summary="Findings summary.",
        key_findings=["finding A", "finding B"],
        sources=[
            Source(url="https://a.example", title="A", snippet="sa"),
            Source(url="https://b.example", title="B", snippet="sb"),
        ],
    )
    assert len(report.sources) == 2
    assert report.summary.startswith("Findings")


def test_research_report_rejects_wrong_types():
    with pytest.raises(ValidationError):
        ResearchReport(summary=123, key_findings=[], sources=[])  # type: ignore[arg-type]

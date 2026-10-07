import hashlib
import json

import pytest
import requests

from pipeline.evidence import fetch, extract, snapshot_sidecars
from pipeline.adapters import ADAPTERS
from pipeline import cli, evidence
from pipeline.definitions import PROGRAMS


class Response:
    def __init__(self, content, code=200):
        self.content = content
        self.status_code = code
        self.url = "https://example.gov/benefit"
        self.headers = {"Content-Type": "text/html"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self, response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


class StatuteSession:
    def __init__(self):
        self.requested = []

    def head(self, *args, **kwargs):
        response = Response(b"")
        response.url = "https://www.govinfo.gov/content/pkg/USCODE-2024-title42/pdf/section.pdf"
        return response

    def get(self, url, **kwargs):
        self.requested.append(url)
        response = Response(b"<h1>Section</h1><p>People are entitled to benefits.</p>")
        response.url = url
        return response


def test_snapshot_reuse_and_failure_preserves_existing(tmp_path):
    seed = {"test": {"seed_id": "test", "adapter": "va", "url": "https://example.gov/benefit", "program_ids": ["va_veterans_pension"]}}
    html = b"<main><h1>Veterans Pension</h1><p>You must meet a rule.</p></main>"
    first = fetch(["test"], seed, tmp_path, Session(Response(html)), pause=0)[0]
    second = fetch(["test"], seed, tmp_path, Session(Response(html)), pause=0)[0]
    assert second == first
    assert first["content_hash"] == hashlib.sha256(html).hexdigest()
    sidecar = snapshot_sidecars(tmp_path, "test")[0]
    assert sidecar.parent.name == "test"
    assert sidecar.stem.count("-") == 2  # YYYY-MM-DD
    candidate = ADAPTERS["va"].extract(html, first["url"])
    assert candidate["candidate_requirements"][0]["locator"] == "Veterans Pension"
    extraction = extract([sidecar], tmp_path / "extracted")[0]
    assert extraction.parent.name == "test"
    assert extraction.stem == sidecar.stem
    with pytest.raises(requests.HTTPError):
        fetch(["test"], seed, tmp_path, Session(Response(b"blocked", 403)), pause=0)
    assert json.loads(sidecar.read_text()) == first


def test_changed_source_same_day_gets_suffix(tmp_path):
    seeds = {"test": {"seed_id": "test", "adapter": "va", "url": "https://example.gov/benefit",
                       "program_ids": ["va_veterans_pension"]}}
    first = fetch(["test"], seeds, tmp_path, Session(Response(b"<h1>One</h1>")), pause=0)[0]
    second = fetch(["test"], seeds, tmp_path, Session(Response(b"<h1>Two</h1>")), pause=0)[0]
    third = fetch(["test"], seeds, tmp_path, Session(Response(b"<h1>Three</h1>")), pause=0)[0]
    assert first["source_id"] != second["source_id"]
    assert third["source_id"] != second["source_id"]
    names = [p.stem for p in snapshot_sidecars(tmp_path, "test")]
    day = names[0][:10]
    assert names == [f"{day}_1", f"{day}_2", f"{day}_3"]
    for path in snapshot_sidecars(tmp_path, "test"):
        meta = json.loads(path.read_text(encoding="utf-8"))
        assert (tmp_path / "test" / f"{path.stem}.html").exists()
        assert meta["snapshot_path"].endswith(f"{path.stem}.html")
    sidecars = snapshot_sidecars(tmp_path, "test")
    outputs = extract(sidecars, tmp_path / "extracted")
    assert len(set(outputs)) == 3
    assert sorted(p.stem for p in outputs) == [f"{day}_1", f"{day}_2", f"{day}_3"]
    assert extract(sidecars, tmp_path / "extracted") == outputs


def test_fetch_paces_same_host_across_calls(tmp_path, monkeypatch):
    now = [0.0]
    sleeps = []
    monkeypatch.setattr(evidence.time, "monotonic", lambda: now[0])

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(evidence.time, "sleep", sleep)
    seeds = {"test": {"seed_id": "test", "adapter": "va", "url": "https://example.gov/benefit",
                      "program_ids": ["va_veterans_pension"]}}
    last_host = {}
    session = Session(Response(b"<h1>Pension</h1>"))
    fetch(["test"], seeds, tmp_path, session, last_host=last_host)
    fetch(["test"], seeds, tmp_path, session, last_host=last_host)
    assert sleeps == [1.0]


def test_xml_extraction_keeps_section_locator():
    raw = b"<document><section><title>Eligibility</title><p>Applicants must qualify.</p></section></document>"
    result = ADAPTERS["ssa"].extract(raw, "https://example.gov/rules.xml", "xml")
    assert result["candidate_requirements"][0]["locator"] == "Eligibility"


def test_fetch_all_reports_failure_and_checks_remaining_sources(monkeypatch, capsys):
    seeds = {"first": {}, "second": {}}
    called = []
    monkeypatch.setattr(cli, "manifest", lambda: seeds)

    def fake_fetch(ids, _seeds, last_host):
        called.extend(ids)
        if ids[0] == "first":
            raise ValueError("blocked")
        return [{"source_id": "second-hash", "fetched_at": "2026-01-01T00:00:00Z"}]

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    with pytest.raises(SystemExit) as error:
        cli.main(["fetch", "--all"])
    assert error.value.code == 1
    assert called == ["first", "second"]
    report = json.loads(capsys.readouterr().out)
    assert [entry["status"] for entry in report] == ["failed", "saved"]


def test_statute_link_resolves_to_official_html(tmp_path):
    seeds = {"law": {"seed_id": "law", "adapter": "statute", "url": "https://www.govinfo.gov/link/uscode/42/402",
                     "program_ids": ["social_security_retirement"]}}
    session = StatuteSession()
    result = fetch(["law"], seeds, tmp_path, session, pause=0)[0]
    assert session.requested == ["https://www.govinfo.gov/content/pkg/USCODE-2024-title42/html/section.htm"]
    assert result["document_type"] == "html"


def test_direct_regulation_pdf_does_not_resolve_as_us_code(tmp_path):
    url = "https://www.govinfo.gov/content/pkg/CFR-2025-title38-vol1/pdf/CFR-2025-title38-vol1-sec3-12a.pdf"
    seeds = {"regulation": {"seed_id": "regulation", "adapter": "statute", "url": url,
                             "program_ids": ["va_veterans_pension"]}}

    class PdfSession:
        def head(self, *_args, **_kwargs):
            raise AssertionError("direct PDFs do not need link resolution")

        def get(self, requested_url, **_kwargs):
            assert requested_url == url
            response = Response(b"%PDF-synthetic")
            response.url = url
            response.headers["Content-Type"] = "application/pdf"
            return response

    result = fetch(["regulation"], seeds, tmp_path, PdfSession(), pause=0)[0]
    assert result["document_type"] == "pdf"


def test_failed_fetch_and_extraction_keep_existing_evidence_and_reviewed_documents(tmp_path, monkeypatch):
    seeds = {"test": {"seed_id": "test", "adapter": "va", "url": "https://example.gov/benefit",
                      "program_ids": ["va_veterans_pension"]}}
    html = b"<main><h1>Veterans Pension</h1><p>Existing guidance.</p></main>"
    raw_dir = tmp_path / "raw"
    core_dir = tmp_path / "core"
    fetch(["test"], seeds, raw_dir, Session(Response(html)), pause=0)
    sidecar = snapshot_sidecars(raw_dir, "test")[0]
    extraction = extract([sidecar], core_dir)[0]
    tracked = [sidecar, raw_dir / "test" / f"{sidecar.stem}.html", extraction]
    tracked.extend(PROGRAMS.glob("*.json"))
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}

    with pytest.raises(requests.HTTPError):
        fetch(["test"], seeds, raw_dir, Session(Response(b"blocked", 403)), pause=0)

    class BrokenAdapter:
        def extract(self, *_):
            raise ValueError("injected extraction failure")

    monkeypatch.setitem(ADAPTERS, "va", BrokenAdapter())
    with pytest.raises(ValueError, match="injected extraction failure"):
        extract([sidecar], core_dir)
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked} == before



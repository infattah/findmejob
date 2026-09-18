import json
from argparse import Namespace
from pathlib import Path

from findmejob.cli import cmd_ingest, cmd_init
from findmejob.config import load_config
from findmejob.pipeline import run_search
from findmejob.tracker import Tracker

ROOT = Path(__file__).parent.parent


def test_init_then_ingest_updates_config(tmp_path):
    assert cmd_init(Namespace(dir=str(tmp_path))) == 0
    cv = ROOT / "sample_data" / "master_cv.example.md"
    assert cmd_ingest(Namespace(dir=str(tmp_path), cv=str(cv))) == 0
    cfg = load_config(tmp_path)
    assert cfg.profile["master_cv"] == "data/profile/master_cv.md"
    assert cfg.resolve(cfg.profile["master_cv"]).exists()


def test_relative_json_source_is_project_relative(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    jobs = [{"title": "Marketer", "company": "Example"}]
    (tmp_path / "data" / "jobs.json").write_text(json.dumps(jobs))
    (tmp_path / "config.json").write_text(json.dumps({
        "search": {"sources": [{"type": "jsonfile", "path": "data/jobs.json"}]}
    }))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    cfg = load_config(tmp_path)
    tracker = Tracker(cfg.db_path)
    assert run_search(cfg, tracker)["fetched"] == 1

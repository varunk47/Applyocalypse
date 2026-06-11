"""Tests for runner.py argparse: verifies all CLI arguments are accepted."""
from __future__ import annotations

import pytest

from applyocalypse_automation.runner import build_parser


def test_required_args_only() -> None:
    args = build_parser().parse_args(["--run-id", "abc-123", "--work-dir", "/tmp/run"])
    assert args.run_id == "abc-123"
    assert args.work_dir == "/tmp/run"
    assert args.job_url is None
    assert args.job_text_file is None
    assert args.job_metadata_file is None
    assert args.profile_json_file is None
    assert args.cover_letter_sample_file is None
    assert args.output_dir is None


def test_cover_letter_sample_file_is_accepted() -> None:
    args = build_parser().parse_args([
        "--run-id", "run-1",
        "--work-dir", "/tmp/run",
        "--cover-letter-sample-file", "/tmp/cover-letter-sample.txt",
    ])
    assert args.cover_letter_sample_file == "/tmp/cover-letter-sample.txt"


def test_cover_letter_sample_file_absent_defaults_to_none() -> None:
    args = build_parser().parse_args(["--run-id", "r", "--work-dir", "/w"])
    assert args.cover_letter_sample_file is None


def test_all_args_together() -> None:
    args = build_parser().parse_args([
        "--run-id", "run-99",
        "--work-dir", "/w",
        "--job-url", "https://example.com/job/123",
        "--job-text-file", "/w/job.txt",
        "--job-metadata-file", "/w/job-target.json",
        "--profile-json-file", "/w/canonical-profile.json",
        "--cover-letter-sample-file", "/w/cover-letter-sample.txt",
        "--output-dir", "/output",
    ])
    assert args.run_id == "run-99"
    assert args.job_url == "https://example.com/job/123"
    assert args.job_text_file == "/w/job.txt"
    assert args.job_metadata_file == "/w/job-target.json"
    assert args.profile_json_file == "/w/canonical-profile.json"
    assert args.cover_letter_sample_file == "/w/cover-letter-sample.txt"
    assert args.output_dir == "/output"


def test_missing_required_run_id_raises() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--work-dir", "/w"])


def test_missing_required_work_dir_raises() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--run-id", "r"])

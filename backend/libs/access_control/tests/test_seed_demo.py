"""Run the handoff demonstration against all checked-in synthetic source fixtures."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def demo_report():
    script = Path(__file__).resolve().parents[1] / "examples" / "revocation_demo.py"
    run = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


def test_actual_corpus_revocation_and_pre_model_filter(demo_report):
    report = demo_report
    assert report["documents"] == 11
    assert report["before_board_allowed"] and not report["after_board_allowed"]
    assert report["outsider_allowed_count"] == 0
    assert not report["revoked_body_in_model_context"]
    assert report["audit_rule"] == "R7:confidential"


@pytest.mark.parametrize(
    "actor,expected",
    [
        (
            "alex.tan",
            {
                "CONF-OPS-1007",
                "CONF-OPS-1042",
                "1VendorListExampleHarbor",
                "PAY-150",
                "C_GENERAL:2026-10-10",
                "C_GENERAL:2026-10-11",
            },
        ),
        (
            "john.tan",
            {
                "CONF-OPS-1007",
                "CONF-OPS-1088",
                "CONF-OPS-1042",
                "<20261010.cutover.4417@example-harbor.com>",
                "1BoardDeckQ3ExampleHarbor",
                "1VendorListExampleHarbor",
                "PAY-142",
                "PAY-150",
                "C_GENERAL:2026-10-10",
                "C_GENERAL:2026-10-11",
                "C_TREASURY_OPS:2026-10-09",
            },
        ),
        ("sam.lee", {"1VendorListExampleHarbor", "C_GENERAL:2026-10-10", "C_GENERAL:2026-10-11"}),
        ("root.admin", {"1BoardDeckQ3ExampleHarbor", "1VendorListExampleHarbor"}),
        (
            "jordan.lim",
            {
                "CONF-OPS-1007",
                "CONF-OPS-1088",
                "CONF-OPS-1042",
                "<20261010.cutover.4417@example-harbor.com>",
                "1VendorListExampleHarbor",
                "PAY-142",
                "PAY-150",
                "C_GENERAL:2026-10-10",
                "C_GENERAL:2026-10-11",
                "C_TREASURY_OPS:2026-10-09",
            },
        ),
        ("mei.chen", set()),
    ],
)
def test_actual_persona_document_visibility_matrix(demo_report, actor, expected):
    assert set(demo_report["visibility_before_revocation"][actor]) == expected

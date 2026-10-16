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
    assert report["documents"] == 24
    assert report["before_board_allowed"] and not report["after_board_allowed"]
    assert report["outsider_allowed_ids"] == ["1RailBTestPlanExampleHarbor"]
    assert not report["revoked_body_in_model_context"]
    assert report["audit_rule"] == "R7:confidential"


@pytest.mark.parametrize(
    "story,decision,rule",
    [
        ("inactive_principal", "deny", "R1:inactive_principal"),
        ("ethical_wall_deny", "deny", "R2:explicit_deny"),
        ("group_grant", "allow", "R5:explicit_grant"),
        ("role_grant", "allow", "R5:explicit_grant"),
        ("restricted_page_owner", "allow", "R3:owner"),
        ("inherited_confluence_restriction", "deny", "R8:confluence"),
        ("expired_drive_share", "deny", "R8:gdrive"),
        ("live_drive_share", "allow", "R8:gdrive"),
        ("link_only_drive_share", "deny", "R8:gdrive"),
        ("direct_message_outsider", "deny", "R8:slack"),
        ("email_bcc", "allow", "R8:email"),
        ("admin_without_source_access", "deny", "R8:slack"),
    ],
)
def test_corpus_exercises_each_access_story(demo_report, story, decision, rule):
    result = demo_report["access_stories"][story]
    assert (result["decision"], result["rule"]) == (decision, rule)


PUBLIC_SLACK = {"C_GENERAL:2026-10-10", "C_GENERAL:2026-10-11", "C_PAYMENTS_ENG:2026-10-11"}
OPS_SPACE = {"CONF-OPS-1007", "CONF-OPS-1031", "CONF-OPS-1042", "CONF-OPS-1120"}
OPS_FINANCE_ONLY = {"CONF-OPS-1088", "CONF-OPS-1104"}
PAY_OPEN = {"PAY-150", "PAY-155"}
VENDORS = "1VendorListExampleHarbor"
TEST_PLAN = "1RailBTestPlanExampleHarbor"
DUE_DILIGENCE = "1VegalineDueDiligenceExampleHarbor"
ORIONIX = "1OrionixRenewalBriefExampleHarbor"
CUTOVER_EMAIL = "<20261010.cutover.4417@example-harbor.com>"
APPROVAL_EMAIL = "<20261012.approval.5120@example-harbor.com>"
FINANCE_OPS = {
    *PUBLIC_SLACK,
    *OPS_SPACE,
    *OPS_FINANCE_ONLY,
    *PAY_OPEN,
    "PAY-142",
    "C_TREASURY_OPS:2026-10-09",
    "CONF-COMP-2001",
    VENDORS,
    TEST_PLAN,
    DUE_DILIGENCE,
    "1RailBSupportFaqExampleHarbor",
    CUTOVER_EMAIL,
    APPROVAL_EMAIL,
}
COMPLIANCE = {*PUBLIC_SLACK, "CONF-COMP-2001", "CONF-COMP-2014", VENDORS, DUE_DILIGENCE}


@pytest.mark.parametrize(
    "actor,expected",
    [
        (
            "alex.tan",
            {*PUBLIC_SLACK, *OPS_SPACE, *PAY_OPEN, VENDORS, TEST_PLAN, ORIONIX},
        ),
        # Same groups as Alex; the explicit deny removes only the Orionix brief.
        ("ravi.kumar", {*PUBLIC_SLACK, *OPS_SPACE, *PAY_OPEN, VENDORS, TEST_PLAN}),
        (
            "john.tan",
            {
                *FINANCE_OPS,
                "1BoardDeckQ3ExampleHarbor",
                ORIONIX,
                "D_JOHN_DANIEL:2026-10-11",
            },
        ),
        ("jordan.lim", FINANCE_OPS),
        (
            "daniel.wong",
            {
                *PUBLIC_SLACK,
                VENDORS,
                APPROVAL_EMAIL,
                "1BoardDeckQ3ExampleHarbor",
                ORIONIX,
                "D_JOHN_DANIEL:2026-10-11",
            },
        ),
        ("nora.ibrahim", COMPLIANCE),
        ("sam.lee", COMPLIANCE),
        ("root.admin", {"1BoardDeckQ3ExampleHarbor", VENDORS}),
        ("mei.chen", {TEST_PLAN}),
        ("lena.koh", set()),
    ],
)
def test_actual_persona_document_visibility_matrix(demo_report, actor, expected):
    assert set(demo_report["visibility_before_revocation"][actor]) == expected

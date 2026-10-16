"""Group resolution in the app (D-023): every principal loaded for an access decision has its
nested groups expanded and its platform group ids bound, so a member of a child group reads what
the parent group reads, and a bound platform id never lets a look-alike local name in."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from access_control import GroupDefinition

from app.schemas.domain import Group
from app.seed import SeedSummary, _load_principals
from app.tests.conftest import run

KYC = ("confluence-ops", "runbooks/kyc-refresh")  # page-restricted to finance-ops
ALEX = {"X-Actor-Id": "alex.tan"}
JORDAN = {"X-Actor-Id": "jordan.lim"}
JOHN = {"X-Actor-Id": "john.tan"}


def _kyc(services: Any) -> str:
    return run(services.repo.get_page_by_slug(*KYC)).id


def _join_oncall(services: Any) -> None:
    """Alex joins a new payments-oncall group (direct membership only)."""
    run(services.repo.upsert_group(Group(id="payments-oncall", name="Payments on-call")))
    run(services.repo.set_memberships("alex.tan", ["engineering", "payments-oncall"]))


def test_member_of_a_nested_group_reads_what_its_parent_reads(seeded: Any, client: Any) -> None:
    kyc = _kyc(seeded)
    _join_oncall(seeded)
    assert client.get(f"/api/documents/{kyc}", headers=ALEX).status_code == 404

    run(
        seeded.group_directory.put(
            GroupDefinition(id="payments-oncall", parent_ids=["finance-ops"])
        )
    )
    assert client.get(f"/api/documents/{kyc}", headers=ALEX).status_code == 200
    me = client.get("/api/me", headers=ALEX).json()
    assert me["groups"] == ["engineering", "finance-ops", "payments-oncall"]

    # The access map evaluates every person the same way.
    edges = {
        (e["principal_id"], e["document_id"])
        for e in client.get("/api/access/map", headers=JOHN).json()["edges"]
    }
    assert ("alex.tan", kyc) in edges


def test_a_bound_platform_group_id_replaces_the_local_name(seeded: Any, client: Any) -> None:
    kyc = _kyc(seeded)
    assert client.get(f"/api/documents/{kyc}", headers=JORDAN).status_code == 200

    # Confluence knows Finance Ops as "conf-finance-ops"; the page still says "finance-ops",
    # which on Confluence is now some other group, so it must stop matching (fail closed).
    run(
        seeded.group_directory.put(
            GroupDefinition(id="finance-ops", platform_ids={"confluence": "conf-finance-ops"})
        )
    )
    assert client.get(f"/api/documents/{kyc}", headers=JORDAN).status_code == 404

    # Once the snapshot uses Confluence's own group id, finance-ops members read it again.
    snapshot = run(seeded.permission_store.get_many([kyc]))[kyc]
    raw = snapshot.raw.model_copy(
        update={
            "space_view_groups": ["conf-finance-ops", "engineering"],
            "page_view_groups": ["conf-finance-ops"],
        }
    )
    run(seeded.permission_store.put(kyc, snapshot.model_copy(update={"raw": raw})))
    assert client.get(f"/api/documents/{kyc}", headers=JORDAN).status_code == 200
    assert client.get(f"/api/documents/{kyc}", headers=ALEX).status_code == 404


def test_seed_loads_group_parents_and_platform_ids(services: Any, tmp_path: Path) -> None:
    path = tmp_path / "principals.yaml"
    path.write_text(
        "groups:\n"
        "  - id: finance-ops\n"
        "    name: Finance Ops\n"
        "    platform_ids: { gdrive: finance@corp.example }\n"
        "  - { id: treasury, name: Treasury, parents: [finance-ops] }\n"
        "  - { id: plain, name: Plain }\n"
        "principals: []\n"
    )
    run(_load_principals(services, path, SeedSummary()))
    definitions = {d.id: d for d in run(services.group_directory.list_definitions())}
    assert set(definitions) == {"finance-ops", "treasury"}  # "plain" needs no definition
    assert definitions["treasury"].parent_ids == ["finance-ops"]
    assert definitions["finance-ops"].platform_ids == {"gdrive": "finance@corp.example"}

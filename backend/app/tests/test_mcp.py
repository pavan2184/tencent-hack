"""MCP over streamable HTTP through the real FastAPI app (TestClient with lifespan).

initialize (X-Actor-Id) -> notifications/initialized -> tools/list -> tools/call whoami / query;
identity is per HTTP request, so a call without the header is an `unauthenticated` tool error.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.mcp.server import TOOL_NAMES

PROTOCOL = "2025-06-18"
RUNBOOK_SLUG = "runbooks/payment-rail-failover"
RUNBOOK_OBJ = "CONF-OPS-1042"
DECK_OBJ = "1BoardDeckQ3ExampleHarbor"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _messages(response: Any) -> list[dict[str, Any]]:
    """JSON body, or the `data:` lines of an SSE body."""
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        return [
            json.loads(line[5:].strip())
            for line in response.text.splitlines()
            if line.startswith("data:") and line[5:].strip()
        ]
    return [response.json()]


class McpSession:
    def __init__(self, client: Any, actor: str | None = "alex.tan", path: str = "/mcp") -> None:
        # The `client` fixture sends a default X-Actor-Id; identity here is explicit per request.
        client.headers.pop("X-Actor-Id", None)
        self.client = client
        self.actor = actor
        self.path = path
        self.session_id: str | None = None
        self._next_id = 0

    def headers(self, actor: str | None) -> dict[str, str]:
        headers = dict(MCP_HEADERS)
        if actor:
            headers["X-Actor-Id"] = actor
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
            headers["mcp-protocol-version"] = PROTOCOL
        return headers

    def post(self, payload: dict[str, Any], *, actor: str | None = "default") -> Any:
        who = self.actor if actor == "default" else actor
        return self.client.post(self.path, json=payload, headers=self.headers(who))

    def request(self, method: str, params: dict[str, Any] | None = None, **kw: Any) -> dict:
        self._next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        response = self.post(payload, **kw)
        assert response.status_code == 200, response.text
        replies = [m for m in _messages(response) if m.get("id") == self._next_id]
        assert replies, response.text
        return replies[-1]

    def initialize(self) -> dict[str, Any]:
        self._next_id += 1
        response = self.post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            }
        )
        assert response.status_code == 200, response.text
        self.session_id = response.headers.get("mcp-session-id")
        reply = _messages(response)[-1]
        ack = self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert ack.status_code in (200, 202), ack.text
        return reply

    def call(self, name: str, arguments: dict[str, Any] | None = None, **kw: Any) -> dict:
        reply = self.request("tools/call", {"name": name, "arguments": arguments or {}}, **kw)
        assert "result" in reply, reply
        return reply["result"]


def _payload(result: dict[str, Any]) -> Any:
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    return json.loads(result["content"][0]["text"])


def _error(result: dict[str, Any]) -> dict[str, Any]:
    assert result.get("isError") is True, result
    return json.loads(result["content"][0]["text"])["error"]


@pytest.fixture
def mcp_session(seeded: Any, client: Any) -> McpSession:
    session = McpSession(client)
    reply = session.initialize()
    assert reply["result"]["serverInfo"]["name"] == "internal-brain"
    assert session.session_id, "stateful streamable HTTP must issue an mcp-session-id"
    return session


def test_tools_list_has_every_tool(mcp_session: McpSession) -> None:
    reply = mcp_session.request("tools/list", {})
    names = {tool["name"] for tool in reply["result"]["tools"]}
    assert names == set(TOOL_NAMES)


def test_whoami_resolves_the_header_actor(mcp_session: McpSession) -> None:
    me = _payload(mcp_session.call("whoami"))
    assert me["id"] == "alex.tan"
    other = _payload(mcp_session.call("whoami", actor="priya.nair"))
    assert other["id"] == "priya.nair"


def test_actor_query_param_is_accepted(seeded: Any, client: Any) -> None:
    session = McpSession(client, actor=None, path="/mcp/?actor=sam.lee")
    session.initialize()
    assert _payload(session.call("whoami"))["id"] == "sam.lee"


def test_missing_or_unknown_actor_is_a_tool_error(mcp_session: McpSession) -> None:
    assert _error(mcp_session.call("whoami", actor=None))["code"] == "unauthenticated"
    assert _error(mcp_session.call("whoami", actor="nobody.here"))["code"] == "unknown_actor"


def test_query_returns_the_governed_envelope(mcp_session: McpSession) -> None:
    envelope = _payload(mcp_session.call("query", {"query": "payment rail failover"}))
    assert envelope["audit_id"]
    assert isinstance(envelope["citations"], list)
    assert envelope["freshness_receipt"] is not None
    assert "answer" in envelope


def test_tool_calls_are_audited(seeded: Any, mcp_session: McpSession) -> None:
    from app.tasks.common import run_async

    mcp_session.call("whoami")
    events = run_async(seeded.repo.list_audit_events(action="mcp.whoami", actor_id="alex.tan"))
    assert events, "mcp.whoami was not audited"
    assert len(events[0].payload["args_hash"]) == 64
    assert events[0].payload["outcome"] == "ok"


def test_denied_page_looks_missing(mcp_session: McpSession) -> None:
    denied = _error(mcp_session.call("get_page", {"slug": "files/board-deck-q3"}, actor="mei.chen"))
    missing = _error(
        mcp_session.call("get_page", {"slug": "files/does-not-exist"}, actor="mei.chen")
    )
    assert denied["code"] == missing["code"] == "not_found"
    assert denied["message"] == missing["message"]


def test_audit_lookup_requires_auditor(mcp_session: McpSession) -> None:
    envelope = _payload(mcp_session.call("query", {"query": "payment rail failover"}))
    forbidden = _error(mcp_session.call("audit_lookup", {"audit_id": envelope["audit_id"]}))
    assert forbidden["code"] == "forbidden"
    event = _payload(
        mcp_session.call("audit_lookup", {"audit_id": envelope["audit_id"]}, actor="sam.lee")
    )
    assert event["id"] == envelope["audit_id"]


def test_sources_list_redacts_secrets(seeded: Any, mcp_session: McpSession) -> None:
    from app.tasks.common import run_async

    source = run_async(seeded.repo.get_source("confluence-ops"))
    run_async(
        seeded.repo.upsert_source(
            source.model_copy(update={"config": {**source.config, "webhook_secret": "x"}})
        )
    )
    listing = _payload(mcp_session.call("sources_list"))
    assert any(item["id"] == "confluence-ops" for item in listing["items"])
    assert "webhook_secret" not in json.dumps(listing)


def test_every_tool_runs_through_the_governed_services(seeded: Any, client: Any) -> None:
    """Happy path (and the key refusal) for each remaining tool, as the right persona."""
    s = McpSession(client)
    s.initialize()

    def ok(name: str, arguments: dict[str, Any] | None = None, actor: str = "alex.tan") -> Any:
        result = s.call(name, arguments, actor=actor)
        assert result.get("isError") is not True, (name, result)
        return _payload(result)

    def err(name: str, arguments: dict[str, Any], actor: str = "alex.tan") -> str:
        return _error(s.call(name, arguments, actor=actor))["code"]

    query = "payment rail failover"
    assert ok("search", {"query": query})["results"]
    assert isinstance(ok("assemble_evidence", {"query": query}), dict)

    meta = ok("get_page", {"slug": RUNBOOK_SLUG})
    assert meta["slug"] == RUNBOOK_SLUG and "compiled_truth" not in meta
    assert (
        "Rail-B"
        in ok("get_page", {"slug": RUNBOOK_SLUG, "include_content": True})["compiled_truth"]
    )

    # Uploads: owner forced to the caller; frontmatter owner/permissions ignored.
    spoof = (
        "---\nowner: priya.nair\npermissions: {kind: upload, owner_principal_id: priya.nair}\n---\n"
    )
    put = ok("put_page", {"slug": "notes/mcp-test", "content": spoof + "# MCP note\n\nHello."})
    assert put["document"]["owner_principal_id"] == "alex.tan"
    assert put["document"]["slug"] == "notes/mcp-test"
    assert err("put_page", {"slug": "x", "content": "# x", "source_id": "confluence-ops"}) == (
        "forbidden"
    )
    captured = ok("capture", {"content": "A quick thought."})
    assert captured["document"]["slug"].startswith("inbox/2026-10-12-")

    uploads = ok("list_pages", {"source_id": "uploads"})
    assert {i["slug"] for i in uploads["items"]} >= {"notes/mcp-test"}
    assert {i["slug"] for i in ok("list_pages", {"type": "runbook"})["items"]} >= {RUNBOOK_SLUG}

    entry = ok(
        "add_timeline_entry",
        {"slug": RUNBOOK_SLUG, "date": "2026-10-12", "summary": "Failover drill run"},
    )
    assert entry["summary"] == "Failover drill run"
    timeline = ok("get_timeline", {"slug": RUNBOOK_SLUG, "after": "2026-10-12"})
    assert [e["summary"] for e in timeline["items"]] == ["Failover drill run"]

    logged = ok(
        "log_ingest",
        {
            "source_type": "meeting",
            "source_ref": "mtg-1",
            "pages_updated": ["notes/mcp-test"],
            "summary": "Weekly sync",
        },
    )
    assert logged["actor_id"] == "alex.tan"

    assert any(i["id"] == "confluence-ops" for i in ok("sources_list")["items"])
    assert isinstance(ok("sources_status", {"source_id": "confluence-ops"}), dict)
    assert err("sources_add", {"id": "slack-live", "kind": "slack"}) == "forbidden"
    added = ok("sources_add", {"id": "slack-live", "kind": "slack"}, actor="root.admin")
    assert added["id"] == "slack-live"

    assert isinstance(ok("freshness_status", {"source_id": "confluence-ops"}), dict)
    obj = ok("freshness_status", {"source_id": "confluence-ops", "external_object_id": RUNBOOK_OBJ})
    assert obj["slug"] == RUNBOOK_SLUG and obj["evaluation"] is not None

    verify_args = {"source_id": "confluence-ops", "external_object_id": RUNBOOK_OBJ}
    assert err("verify_freshness", verify_args) == "forbidden"  # employee
    verified = ok("verify_freshness", verify_args, actor="priya.nair")  # manager
    assert verified["verification_result"] == "stale"

    hidden = ok("request_access", {"slug": "files/board-deck-q3", "reason": "Q3"}, actor="mei.chen")
    absent = ok("request_access", {"slug": "files/never-was", "reason": "Q3"}, actor="mei.chen")
    assert hidden == absent


def test_object_tools_do_not_reveal_hidden_documents(mcp_session: McpSession) -> None:
    """A denied object and a missing one produce the same tool error (code and message)."""
    for tool in ("freshness_status", "verify_freshness"):
        denied = _error(
            mcp_session.call(
                tool,
                {"source_id": "gdrive-finance", "external_object_id": DECK_OBJ},
                actor="mei.chen",
            )
        )
        missing = _error(
            mcp_session.call(
                tool,
                {"source_id": "gdrive-finance", "external_object_id": "nope"},
                actor="mei.chen",
            )
        )
        assert (denied["code"], denied["message"]) == (missing["code"], missing["message"])
        assert denied["code"] == "not_found"

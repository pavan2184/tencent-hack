"""Group resolution: nested groups, and each group's id on every platform.

A directory lists the groups a principal was added to directly. Platforms also let members of a
nested group read what its parent groups can read (a member of ``treasury`` inside
``finance-ops`` reads what ``finance-ops`` reads), and each platform names the same group its own
way (Drive by the group's address, Confluence and Jira by their own group ids).
``resolve_groups`` turns direct membership into everything the policy must match:

- ``Principal.groups``: the direct groups plus every ancestor, sorted. Local grants, uploads and
  external MCP allow-lists match these.
- ``Principal.platform_groups[kind]``: for each platform where at least one of those groups has a
  bound id, that bound id per group, or the local id for a group without one. The policy matches
  Confluence, Jira and Drive group entries against it.

A bound platform id replaces the local id on that platform, exactly as a bound platform identity
replaces the local principal id, so a local group name can never match an unrelated platform
group that happens to share it. Parent ids without a definition still count as groups. Cycles are
harmless. Pure and synchronous: the app loads the definitions and calls this per principal.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from access_control.models import Principal
from access_control.permissions import SourceKind


class GroupDefinition(BaseModel):
    """One group's place in the hierarchy and its id on each platform it exists on."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    # Groups whose members include every member of this group.
    parent_ids: list[str] = Field(default_factory=list)
    # SourceKind value → this group's id on that platform (e.g. gdrive → "leadership@corp.com").
    platform_ids: dict[SourceKind, str] = Field(default_factory=dict)


def _index(
    definitions: Iterable[GroupDefinition] | Mapping[str, GroupDefinition],
) -> dict[str, GroupDefinition]:
    if isinstance(definitions, Mapping):
        return dict(definitions)
    return {d.id: d for d in definitions}


def expand_groups(
    direct: Iterable[str],
    definitions: Iterable[GroupDefinition] | Mapping[str, GroupDefinition],
) -> list[str]:
    """``direct`` plus every ancestor group, sorted and de-duplicated."""
    by_id = _index(definitions)
    seen: set[str] = set()
    stack = [g for g in direct if g]
    while stack:
        group = stack.pop()
        if group in seen:
            continue
        seen.add(group)
        definition = by_id.get(group)
        if definition is not None:
            stack.extend(p for p in definition.parent_ids if p and p not in seen)
    return sorted(seen)


def resolve_groups(
    principal: Principal,
    definitions: Iterable[GroupDefinition] | Mapping[str, GroupDefinition],
) -> Principal:
    """A copy of ``principal`` with nested groups expanded and platform group ids bound."""
    by_id = _index(definitions)
    groups = expand_groups(principal.groups, by_id)
    kinds = {str(kind) for group in groups if group in by_id for kind in by_id[group].platform_ids}
    platform_groups = {
        kind: sorted(
            {by_id[g].platform_ids.get(SourceKind(kind), g) if g in by_id else g for g in groups}
        )
        for kind in sorted(kinds)
    }
    return principal.model_copy(
        update={"groups": groups, "platform_groups": platform_groups}, deep=True
    )

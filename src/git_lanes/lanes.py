from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Commit:
    hash: str
    parents: list[str]
    author: str
    author_at: int
    subject: str
    body: str = ""
    refs: list[str] = field(default_factory=list)
    uncommitted: bool = False
    stash: bool = False
    lane: int = 0
    edges: list[dict] = field(default_factory=list)
    through: list[int] = field(default_factory=list)
    joins: list[int] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "hash": self.hash,
            "parents": self.parents,
            "author": self.author,
            "author_at": self.author_at,
            "subject": self.subject,
            "refs": self.refs,
            "uncommitted": self.uncommitted,
            "stash": self.stash,
            "lane": self.lane,
            "edges": self.edges,
            "through": self.through,
            "joins": self.joins,
        }


def _alloc(state: list[str | None]) -> int:
    for i, h in enumerate(state):
        if h is None:
            return i
    state.append(None)
    return len(state) - 1


def assign_lanes(commits: list[Commit]) -> None:
    """Assign Git Graph-style lanes. `commits` must be newest-first."""
    lanes: list[str | None] = []

    for c in commits:
        found = [i for i, h in enumerate(lanes) if h == c.hash]
        if not found:
            i = _alloc(lanes)
            lanes[i] = c.hash
            found = [i]
        c.lane = found[0]
        c.joins = found[1:]

        next_state = list(lanes)
        for i in found[1:]:
            next_state[i] = None

        edges: list[dict] = []
        if c.parents:
            next_state[c.lane] = c.parents[0]
            edges.append(
                {"from_lane": c.lane, "to_lane": c.lane, "kind": "parent1"}
            )
            for p in c.parents[1:]:
                existing = [i for i, h in enumerate(next_state) if h == p]
                if existing:
                    to = existing[0]
                else:
                    to = None
                    for i in found[1:]:
                        if next_state[i] is None:
                            to = i
                            break
                    if to is None:
                        to = _alloc(next_state)
                    next_state[to] = p
                edges.append(
                    {"from_lane": c.lane, "to_lane": to, "kind": "merge"}
                )
        else:
            next_state[c.lane] = None

        while next_state and next_state[-1] is None:
            next_state.pop()

        c.edges = edges
        c.through = [i for i, h in enumerate(next_state) if h is not None]
        lanes = next_state

"""The local share of a divert (contract R22.1): the fraction of the goods
passing a diverter that its branch takes, as the shared item stream
animates it (operators/stream.py). Pure: the stream tree comes in as plain
data, so a unit test can build any layout.

Every slot of a stream carries an OWNER (the main line 0, a populated
feeder k) and a route KEY. The keys are atoms with weights: the exit
portions of share routing (their widths), the item classes of class
routing (equal weights), or one atom when nothing routes by key. A rule
-- a diverter at stream coordinate u -- takes the slots whose owner is in
its mask and whose key is one of its atoms; a slot leaves at the first
rule it meets. So the goods on a line just before a point are the atoms of
each owner that reached it, and a branch's local share is the weight it
takes over the weight passing just before its diverter. Rules and merges
at the same place count as one split (R22.1: ports within 1 mm of the
same u_m are one boundary; diverts leave the section before it)."""
from __future__ import annotations

from dataclasses import dataclass, field

SAME_PLACE_M = 1e-3


@dataclass(frozen=True)
class Rule:
    u: float  # stream coordinate of the diverter
    atoms: frozenset  # the keys it takes
    mask: int  # the owners it takes from (bit k = owner k)


@dataclass
class Member:
    kind: str | None  # None (the root), 'MERGE', 'DIVERTER' or 'CONTINUE'
    parent: str | None = None
    at_u: float = 0.0  # MERGE: where its goods reach the parent's path; DIVERTER / CONTINUE: where it leaves it
    owner: int = -1  # MERGE: its own goods' owner (-1: an unpopulated feeder)
    rule: Rule | None = None  # DIVERTER: what it takes
    routes: list = field(default_factory=list)  # the rules that apply on this line's path


def _entry_into(members: dict, owner_line: dict, owner: int, name: str):
    """Where the goods of `owner` come onto line `name`'s path through a chain
    of merges (a feeder of it, or a feeder of such a feeder), else None."""
    cur = owner_line.get(owner)
    seen = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        m = members.get(cur)
        if m is None or m.kind != 'MERGE':
            return None
        if m.parent == name:
            return m.at_u
        cur = m.parent
    return None


def atoms_on(members: dict, owner_line: dict, all_atoms: frozenset, name: str, owner: int, u: float, _depth: int = 0) -> frozenset:
    """The keys of `owner`'s goods on line `name`'s path just before stream
    coordinate u (rules and merges at u itself not yet passed)."""
    m = members.get(name)
    if m is None or _depth > 64:
        return frozenset()
    via = _entry_into(members, owner_line, owner, name)
    if (m.kind is None and owner == 0) or (m.kind == 'MERGE' and m.owner == owner):
        base = all_atoms
    elif via is not None:
        base = all_atoms if via < u - SAME_PLACE_M else frozenset()
    elif m.kind in ('DIVERTER', 'CONTINUE') and m.parent is not None:
        base = atoms_on(members, owner_line, all_atoms, m.parent, owner, m.at_u, _depth + 1)
        if m.kind == 'DIVERTER':
            base = base & m.rule.atoms if (m.rule is not None and (m.rule.mask >> owner) & 1) else frozenset()
    else:
        base = frozenset()
    for r in m.routes:
        if base and r.u < u - SAME_PLACE_M and (r.mask >> owner) & 1:
            base = base - r.atoms
    return base


def local_share(members: dict, owner_line: dict, weights: list, atom_weights: dict, branch: str):
    """The fraction (0..1) of the goods passing branch `branch`'s diverter
    that it takes, or None when nothing passes there (or it is no branch)."""
    m = members.get(branch)
    if m is None or m.kind != 'DIVERTER' or m.parent is None or m.rule is None:
        return None
    all_atoms = frozenset(atom_weights)

    def weight(atoms) -> float:
        return sum(atom_weights[a] for a in atoms)

    passing = taken = 0.0
    for k, w in enumerate(weights):
        if w <= 0.0:
            continue
        here = atoms_on(members, owner_line, all_atoms, m.parent, k, m.at_u)
        if not here:
            continue
        passing += w * weight(here)
        if (m.rule.mask >> k) & 1:
            taken += w * weight(here & m.rule.atoms)
    if passing <= 1e-12:
        return None
    return max(0.0, min(1.0, taken / passing))

"""Carry one project's record to another machine's notebook, and back.

The notebook is machine-wide and lives outside every repository, so a
project worked on from two machines had two records that could not see each
other: each looked complete and was simply missing the other's work. This
writes one project's record into a file in that project's own repository --
`<repo>/.sainpost/<project>.json` -- which travels however the code
does, and reads it into the notebook on the other side.

MERGING, NOT COPYING
Both machines write, in turn. So an import is a merge of two append-only
records, and it can be one only because nothing here is ever edited: a row
either exists or it does not, and the only changes to a row that exists are
one-time transitions -- an attempt closing, a question answered or
superseded, a request decided, a defect queried, replied to or closed. Each
is NULL-to-value, once. An import inserts the rows this notebook lacks and
applies the transitions it has not seen. Nothing it already holds is
overwritten.

LABELS ARE NOT RENUMBERED, AND A NUMBER IS NOT IDENTITY
Labels are cited inside the text of other records ("A22 showed", "R3 was
accepted on"), so a renumbered row would silently change what every sentence
pointing at it means. That is the failure this record exists to stop,
arriving through its own sync. So nothing is renumbered -- and a question or
attempt is matched by what it was made with (its ident), not by its number:
both machines adding to one project without importing first is the ordinary
case, and a number both used arrives after the name of the notebook that
wrote it (Q20@k7m). Two projects under one name that are not one project --
their cards were made separately -- are refused where they share a number.

R and D labels are notebook-wide, not per project, so a second machine with
its own history has its own R5 -- and both machines file requests without
asking each other, so this is the ordinary case, not a mistake. A request or
defect is its number AND what it was created with (store.ident, a hash that
is the same on every machine). One whose number is taken here by a different
record still comes across, under the same number, and prints it with its
hash: R5@3fa2c1. The one that was here first keeps printing bare R5. Nothing
is renumbered and no text is rewritten; what a bare R5 inside carried text
names is worked out where it is read (Store._legend), from the record of
which writing arrived from where.

WHAT IT WRITES TO THE REPOSITORY
The notebook otherwise writes nothing to a repository it observes, and this
is the one exception, made only when asked, one file, in one directory. What
it costs is said at export time: committed while an attempt is open, the
file moves HEAD, and that attempt will close against a different commit
than it opened on -- which the record reports as the code having moved.

The file is a pure function of the record: no timestamp, no host, no local
path. An export that learned nothing leaves the file byte-identical.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from sainpost import rig
from sainpost.store import ANSWER_IS, NoteError, Store, _lab, _now, ident

#: The version this writes. /1 numbered every reference by seq, which was
#: identity only while seq was unique in a project; /2 carries each question
#: and attempt with its ident and the notebook that wrote it, and every
#: reference as an ident. /1 files are still read, by upgrading them in memory.
FORMAT = "sainpost-project/2"
FORMAT_V1 = "sainpost-project/1"
SHARE_DIR = ".sainpost"

# What a row was created with. Compared on every match; any difference means
# the same label names two different things.
Q_MADE = ("text", "supersedes", "created_at")
A_MADE = ("question", "hypothesis", "why_now", "prompted_by", "measure",
          "falsifier", "apparatus", "open_commit", "open_dirty",
          "open_untracked", "created_at")
# A request's and a defect's contents are compared through store.ident, which
# leaves out the names of their two sides: this import may read another
# notebook's name as one of this notebook's. The sides are compared after
# that reading instead.
R_SIDES = (("asked_by", "asked_by"), ("owner_id", "owner"))
D_SIDES = (("reported_by", "reported_by"), ("owner_id", "owner"))

# One-time transitions: (the field that says it happened, every field it set).
Q_CLOSE = ("closed_at", ("status", "answer", "answer_headline", "closed_at"))
A_CLOSE = ("closed_at", ("result", "result_headline", "verdict", "close_commit",
                         "close_dirty", "close_untracked", "closed_at"))
R_CLOSE = ("closed_at", ("decision", "why", "closed_at"))
D_STEPS = (("queried_at", ("query", "asked_by", "queried_at")),
           ("replied_at", ("reply", "replied_at")),
           ("closed_at", ("resolution", "cause", "change", "verify",
                          "invalidates", "fix_commit", "fix_dirty",
                          "fix_untracked", "closed_at")))
#: The writing each defect step is, in the `carried` table.
D_EVENT = {"queried_at": "queried", "replied_at": "replied", "closed_at": "closed"}


def file_name(project: str) -> str:
    """Safe on both platforms. Windows refuses these characters outright."""
    return (re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", project).strip(" .")
            or "project") + ".json"


def target(store: Store, project: str, path: Optional[str] = None) -> Path:
    """Where a project's file goes: a .json path as given, a directory as
    a repository root, and by default the repository the project records."""
    if path and path.strip():
        p = Path(path.strip()).expanduser()
        return p if p.suffix.lower() == ".json" else p / SHARE_DIR / file_name(project)
    row = store._project_row(project)
    if not row["repo"]:
        raise NoteError(
            f"{project!r} records no repository, so there is nowhere to put its "
            f"file by default. Pass path= -- a repository root, or a .json file.")
    if not Path(row["repo"]).is_dir():
        raise NoteError(
            f"{project!r} records its repository as {row['repo']!r}, which does "
            f"not exist on this machine. note_start(project, repo=...) re-points "
            f"a stale path; or pass path= for this export.")
    return Path(row["repo"]) / SHARE_DIR / file_name(project)


# -- reading the record out ----------------------------------------------

def snapshot(store: Store, project: str) -> dict:
    """One project's whole record, in label order, with no row ids in it.

    Ids are this database's own and mean nothing on another machine. Every
    reference is carried as a label instead: a question or attempt by its
    seq within the project, anything across projects by project name.
    """
    db = store.db
    p = store._project_row(project)
    rows = lambda sql, *a: db.execute(sql, a).fetchall()
    # By number and then by ident: two rows can share a number, and the order
    # must not depend on which one this notebook happened to get first, or
    # the same record would export differently on each machine.
    qs = sorted(rows("SELECT * FROM questions WHERE project_id=?", p["id"]),
                key=lambda r: (r["seq"], r["ident"]))
    at = sorted(rows("SELECT * FROM attempts WHERE project_id=?", p["id"]),
                key=lambda r: (r["seq"], r["ident"]))
    qseq = {q["id"]: q["ident"] for q in qs}
    aseq = {a["id"]: a["ident"] for a in at}
    cur = qseq.get(p["current_question"])

    def attempt_ref(aid: Optional[int], full: bool = False) -> Optional[dict]:
        if aid is None:
            return None
        r = db.execute("SELECT a.seq, a.ident, a.created_at, a.hypothesis,"
                       " p.name project FROM attempts a JOIN projects p"
                       " ON p.id=a.project_id WHERE a.id=?", (aid,)).fetchone()
        out = {"project": r["project"], "seq": r["seq"], "ident": r["ident"],
               "created_at": r["created_at"]}
        if full:
            out["hypothesis"] = r["hypothesis"]
        return out

    def notes(table: str, key: str, row_id: int) -> list[dict]:
        return [{"written_by": store._project_name(n["written_by"]),
                 "shown_by": attempt_ref(n["shown_by"]),
                 "text": n["text"], "created_at": n["created_at"]}
                for n in rows(f"SELECT * FROM {table} WHERE {key}=? ORDER BY id", row_id)]

    def by_label(kind: str, table: str, sides: str) -> list:
        # By number and then by hash: two records can share a number, and the
        # order must not depend on which one this notebook happened to get
        # first, or the same record would export differently on each machine.
        return sorted(rows(f"SELECT * FROM {table} WHERE {sides}=? OR owner_id=?",
                           p["id"], p["id"]),
                      key=lambda r: (r["seq"], store._ident_of(kind, r)))

    def superseded(d) -> dict:
        if not d["supersedes"]:
            return {"supersedes": None}
        s = db.execute("SELECT * FROM defects WHERE id=?", (d["supersedes"],)).fetchone()
        # The hash beside the number only where there is one to carry, so a
        # record with none exports byte-identical to what came before it.
        return {"supersedes": s["seq"], "supersedes_ident": store._ident_of("D", s)}

    def cites(kind: str, node_id: int) -> list:
        """What this node was recorded as resting on, by name and by the
        identity of the cited row -- a label alone names a different record
        in another notebook, which is the failure citations exist to stop."""
        def cited(c) -> Optional[str]:
            if c["to_id"] is None:
                return None
            t = "attempts" if c["to_kind"] == "A" else "questions"
            return db.execute(f"SELECT ident FROM {t} WHERE id=?",
                              (c["to_id"],)).fetchone()["ident"]
        return [{"project": c["to_project"], "kind": c["to_kind"],
                 "seq": c["to_seq"], "ident": cited(c),
                 "created_at": c["to_created"],
                 "role": c["role"], "cited_at": c["created_at"]}
                for c in rows("SELECT * FROM citations WHERE kind=? AND node_id=?"
                              " ORDER BY id", kind, node_id)]

    name = store._project_name
    # Projects merged into this one. The other notebook makes the same merge
    # when it imports this, so its agents' old name keeps landing here too.
    gone = [r["name"] for r in rows(
        "SELECT name FROM projects WHERE merged_into=? ORDER BY name", p["id"])]
    return {
        "format": FORMAT,
        "project": {"name": p["name"], "description": p["description"],
                    "stub": bool(p["stub"]), "created_at": p["created_at"],
                    "current_question": cur,
                    **({"absorbed": gone} if gone else {})},
        "questions": [{
            "seq": q["seq"], "ident": q["ident"], "origin": q["origin"],
            "text": q["text"], "headline": q["headline"],
            "status": q["status"],
            "answer": q["answer"], "answer_headline": q["answer_headline"],
            # Whose the answer is, and where a note left it: only where there
            # is something to say, so a record with none exports
            # byte-identical to what came before these existed.
            **({"answer_user_said": q["answer_user_said"]}
               if q["answer_user_said"] else {}),
            "supersedes": qseq.get(q["supersedes"]),
            "superseded_by": qseq.get(q["superseded_by"]),
            "parent": qseq.get(q["parent"]),
            "cites": cites("Q", q["id"]),
            "created_at": q["created_at"], "closed_at": q["closed_at"],
            "postscripts": [{"text": r["text"], "headline": r["headline"],
                             **({"answer_is": r["answer_is"]} if r["answer_is"] else {}),
                             **({"user_said": r["user_said"]} if r["user_said"] else {}),
                             "created_at": r["created_at"]}
                            for r in rows("SELECT * FROM postscripts WHERE"
                                          " question_id=? ORDER BY id", q["id"])],
        } for q in qs],
        "attempts": [{
            "seq": a["seq"], "ident": a["ident"], "origin": a["origin"],
            "question": qseq[a["question_id"]],
            "cites": cites("A", a["id"]),
            "hypothesis": a["hypothesis"], "headline": a["headline"],
            "why_now": a["why_now"],
            "prompted_by": aseq.get(a["prompted_by"]),
            "measure": a["measure"], "falsifier": a["falsifier"],
            "apparatus": a["apparatus"], "result": a["result"],
            "result_headline": a["result_headline"],
            "verdict": a["verdict"],
            "open_commit": a["open_commit"], "open_dirty": a["open_dirty"],
            "open_untracked": a["open_untracked"],
            "close_commit": a["close_commit"], "close_dirty": a["close_dirty"],
            "close_untracked": a["close_untracked"],
            "created_at": a["created_at"], "closed_at": a["closed_at"],
            "notes": [{"shown_by": aseq.get(n["shown_by"]), "text": n["text"],
                       "headline": n["headline"], "created_at": n["created_at"]}
                      for n in rows("SELECT * FROM attempt_notes WHERE"
                                    " attempt_id=? ORDER BY id", a["id"])],
        } for a in at],
        "requests": [{
            "seq": r["seq"], "asked_by": name(r["asked_by"]),
            "owner": name(r["owner_id"]), "wanted": r["wanted"],
            "because": r["because"], "context": r["context"],
            "decision": r["decision"], "why": r["why"],
            "created_at": r["created_at"], "closed_at": r["closed_at"],
            "notes": notes("request_notes", "request_id", r["id"]),
        } for r in by_label("R", "requests", "asked_by")],
        "defects": [{
            "seq": d["seq"], "reported_by": name(d["reported_by"]),
            "owner": name(d["owner_id"]),
            "attempt": attempt_ref(d["attempt_id"], full=True),
            # Only when there is one: a record with no false reading in it
            # exports byte-identical to what came before this field existed.
            **({"reading_in": attempt_ref(d["reading_in"], full=True)}
               if d["reading_in"] else {}),
            "invocation": d["invocation"], "observed": d["observed"],
            "needed": d["needed"],
            **superseded(d),
            "context": d["context"],
            "seen_commit": d["seen_commit"], "seen_dirty": d["seen_dirty"],
            "seen_untracked": d["seen_untracked"],
            "query": d["query"],
            "asked_by": name(d["asked_by"]) if d["asked_by"] else None,
            "queried_at": d["queried_at"], "reply": d["reply"],
            "replied_at": d["replied_at"],
            "resolution": d["resolution"], "cause": d["cause"],
            "change": d["change"], "verify": d["verify"],
            "invalidates": d["invalidates"],
            "fix_commit": d["fix_commit"], "fix_dirty": d["fix_dirty"],
            "fix_untracked": d["fix_untracked"],
            "created_at": d["created_at"], "closed_at": d["closed_at"],
            "notes": notes("defect_notes", "defect_id", d["id"]),
        } for d in by_label("D", "defects", "reported_by")],
    }


def render(data: dict) -> str:
    """UTF-8, LF, keys in the order written. The same record gives the same
    bytes on either platform, so an export that learned nothing is no diff."""
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# -- merging a record in -------------------------------------------------

class _Merge:
    """One import, inside one transaction. Collects what it did and what it
    could not do; raises on the first thing that means the two records
    disagree about the project itself."""

    def __init__(self, store: Store, data: dict, repo: str,
                 rename: Optional[dict[str, str]] = None, file: str = ""):
        self.s, self.db, self.data, self.repo = store, store.db, data, repo
        self.file = file
        self.rename = dict(rename or {})
        # What earlier imports were told another notebook calls a project
        # here. Read on every import, because the other machine goes on
        # writing its own name.
        self.aliases = {r["name"]: r["project"] for r in self.db.execute(
            "SELECT a.name, p.name project FROM aliases a"
            " JOIN projects p ON p.id=a.project_id")}
        # Projects merged into another here: the other machine may still
        # write the old name, and what it wrote belongs where the rows went.
        self.merged = {r["name"]: store._project_row(r["name"])["name"]
                       for r in self.db.execute(
                           "SELECT name FROM projects WHERE merged_into IS NOT NULL")}
        # Merges the file said were made over there, made here by this import.
        self.joined: list[str] = []
        self.applied: dict[str, str] = {}
        self.import_id: Optional[int] = None
        self.added: dict[str, int] = {}
        self.closed: list[str] = []
        self.not_carried: list[str] = []
        self.conflicts: list[str] = []
        self.kept: list[str] = []
        self.beside: list[str] = []
        # Rows that arrived under a number a record here already holds.
        self.qualified: list[str] = []
        # Rows here whose notebook the file named for the first time.
        self.origins = 0
        # (here, there): the project's card was made separately on each side.
        self.separate: Optional[tuple[str, str]] = None
        # Names that became a blank card here beside one differing only in case.
        self.twins: dict[str, str] = {}
        # Rows this import inserted. Their closing came with them and is part
        # of "added"; listing it again as news would bury the one thing the
        # line is for -- what closed over there that was open here.
        self.fresh: set[tuple[str, int]] = set()

    def count(self, what: str, table: str = "", row_id: int = 0) -> None:
        self.added[what] = self.added.get(what, 0) + 1
        if table:
            self.fresh.add((table, row_id))

    def changed(self) -> bool:
        return bool(self.added or self.closed or self.origins or self.joined)

    def carry(self, tbl: str, row_id: int, event: str) -> None:
        """Say that this writing arrived from another notebook. What a bare
        label in it names is read from that, wherever it is printed."""
        self.db.execute("INSERT OR IGNORE INTO carried (tbl, row_id, event, import_id)"
                        " VALUES (?,?,?,?)", (tbl, row_id, event, self.import_row()))

    def import_row(self) -> int:
        if self.import_id is None:
            self.import_id = self.db.execute(
                "INSERT INTO imports (file, project, created_at) VALUES (?,?,?)",
                (self.file, self.name(self.data["project"]["name"]), _now())).lastrowid
        return self.import_id

    # projects ---------------------------------------------------------

    def name(self, name: Optional[str]) -> Optional[str]:
        """A project name as the file writes it, read as this notebook's."""
        to = self.rename.get(name) or self.aliases.get(name)
        if name is None:
            return name
        if not to or to == name:
            return self.merged.get(name, name)
        self.applied[name] = to
        return self.merged.get(to, to)

    def learn_origins(self, names: tuple) -> None:
        """Where the rows of these projects were written, from the file,
        before a merge that tells rows apart by exactly that. A row carried
        in before files said is found by what it was made with."""
        pids = [r["id"] for n in names
                if (r := self.s._project_row(n, required=False, follow=False))]
        marks = ",".join("?" * len(pids))
        for table, rows in (("questions", self.data["questions"]),
                            ("attempts", self.data["attempts"])):
            for r in rows:
                if r.get("origin"):
                    self.origins += self.db.execute(
                        f"UPDATE {table} SET origin=? WHERE ident=? AND origin IS NULL"
                        f" AND project_id IN ({marks})",
                        (r["origin"], r["ident"], *pids)).rowcount

    def absorbed(self, target: str) -> None:
        """Make here the merges the file says were made there. A name the
        file absorbed that this notebook never held is recorded as read as
        the project, so a later file under that name lands in it."""
        for gone in self.data["project"].get("absorbed", []):
            if self.name(gone) == target:
                continue
            if gone in self.aliases:
                self.conflicts.append(
                    f"the file says {gone!r} was merged into {target!r}, and here "
                    f"{gone!r} is already read as {self.aliases[gone]!r}")
                continue
            row = self.s._project_row(gone, required=False, follow=False)
            if row is not None:
                self.learn_origins((target, gone))
            if row is None:
                self.db.execute(
                    "INSERT INTO aliases (name, project_id, import_id) VALUES (?,?,?)",
                    (gone, self.s._project_row(target)["id"], self.import_row()))
                self.aliases[gone] = target
                continue
            try:
                self.s._merge(target, gone)
            except NoteError as e:
                self.conflicts.append(
                    f"the file says {gone!r} was merged into {target!r} over there, "
                    f"and here that merge cannot be made: {e}")
                continue
            self.merged[gone] = target
            self.joined.append(f"{gone!r} into {target!r}, as the other notebook did")

    def party(self, name: str) -> int:
        """A project named in a request or defect. Created as a blank card
        if this notebook has never heard of it, as a referral would."""
        local = self.name(name)
        if self.s._project_row(local, required=False) is None and local not in self.twins:
            twin = self.db.execute("SELECT name FROM projects WHERE lower(name)=lower(?)",
                                   (local,)).fetchone()
            if twin is not None:
                self.twins[local] = twin["name"]
        return self.s._referral_stub(local)["id"]

    def project(self) -> int:
        card = self.data["project"]
        name = self.name(card["name"])
        row = self.s._project_row(name, required=False)
        if row is None:
            # Nothing joins a file to a project by anything but its exact
            # name (or a rename= saying so), so a case variant or a second
            # record of the same repository becomes a new project silently --
            # unless it is said.
            for o in self.db.execute(
                    "SELECT name, repo FROM projects WHERE lower(name)=lower(?)"
                    " OR (repo<>'' AND repo=?) ORDER BY name",
                    (name, self.repo)):
                why = [w for w, hit in (
                    ("records the same repository", self.repo and o["repo"] == self.repo),
                    ("has a name that differs from this one only in case",
                     o["name"].lower() == name.lower())) if hit]
                self.beside.append(
                    f"{o['name']!r} {' and '.join(why)}. The import does not join "
                    f"them: {name!r} becomes a second project beside it, "
                    f"and note_projects lists both"
                    + (f". rename={{{name!r}: {o['name']!r}}} reads it as that one"
                       if o["name"].lower() == name.lower() else ""))
            cur = self.db.execute(
                "INSERT INTO projects (name, description, repo, stub, created_at)"
                " VALUES (?,?,?,?,?)",
                (name, card["description"] or "", self.repo,
                 1 if card.get("stub") else 0, card["created_at"]))
            self.count("project")
            return cur.lastrowid
        # A file under a name merged into another here is that name's own
        # record, still being written on a machine that has not merged yet.
        # Its card is the merged project's, and that is the one to compare.
        was = self.s._project_row(card["name"], required=False, follow=False)
        if was is not None and was["merged_into"] is not None:
            if (not was["stub"] and not card.get("stub")
                    and (was["created_at"], was["description"] or "")
                    != (card["created_at"], card["description"] or "")):
                self.separate = (f"made {was['created_at']}",
                                 f"made {card['created_at']}")
            return row["id"]
        if row["stub"] and not card.get("stub"):
            # The first time its own team's card reaches this notebook. The
            # same once-only adoption note_start does, for the same reason.
            self.db.execute(
                "UPDATE projects SET description=?, stub=0,"
                " repo=CASE WHEN repo='' THEN ? ELSE repo END WHERE id=?",
                (card["description"] or "", self.repo, row["id"]))
            self.closed.append("the project card, which was blank here")
        elif (not row["stub"] and not card.get("stub")
              and (row["description"] or "") != (card["description"] or "")):
            self.kept.append("the description: a card is a claim and this "
                             "notebook's stays as written")
        # A card is made once, and carried: the same project has the same one
        # on every machine, to the second and to the word.
        if (not row["stub"] and not card.get("stub")
                and (row["created_at"], row["description"] or "")
                != (card["created_at"], card["description"] or "")):
            self.separate = (f"made {row['created_at']}", f"made {card['created_at']}")
        return row["id"]

    # the one-time steps ------------------------------------------------

    def step(self, label: str, table: str, local: dict, incoming: dict,
             fields: tuple, key: str, values: dict, fatal: bool) -> bool:
        """Apply one NULL-to-value transition, or see that it already
        happened the same way, or say that it happened differently. True
        when it wrote."""
        if incoming.get(key) is None:
            return False
        if local[key] is None:
            sets = ", ".join(f"{f}=?" for f in fields)
            self.db.execute(f"UPDATE {table} SET {sets} WHERE id=?",
                            [values.get(f) for f in fields] + [local["id"]])
            if (table, local["id"]) not in self.fresh:
                self.closed.append(label)
            return True
        if any(local[f] != values.get(f) for f in fields):
            msg = (f"{label}: closed differently on each side "
                   f"({local[key]} here, {incoming[key]} in the file)")
            (self.conflicts if fatal else self.not_carried).append(
                msg if fatal else msg + " -- this notebook's is kept")
        return False

    # questions and attempts -------------------------------------------
    #
    # Matched by what they were made with (ident), not by number. A number
    # is what each notebook gave its own rows, and two notebooks working one
    # project both have a Q20. The one arriving second prints after the name
    # of the notebook that wrote it; nothing is renumbered.

    def _qual(self, kind: str, pid: int, row: dict) -> Optional[str]:
        """How a question or attempt arriving now prints here: bare when its
        number is free, otherwise after the name of the notebook that wrote
        it. None, with the conflict said, when neither can be true."""
        table, what, body = (("questions", "question", "text") if kind == "Q"
                             else ("attempts", "attempt", "hypothesis"))
        held = {r["qual"]: r for r in self.db.execute(
            f"SELECT * FROM {table} WHERE project_id=? AND seq=?", (pid, row["seq"]))}
        if "" not in held:
            return ""
        origin = row.get("origin")
        if self.separate:
            # Two machines on one project hold the same card: it was made once
            # and carried. Two cards under one name are two investigations,
            # and a number both use is where that shows.
            here, there = self.separate
            self.conflicts.append(
                f"{kind}{row['seq']} is a different {what} on each side. Here: "
                f"{_head(held[''][body])}  File: {_head(row[body])}. The project "
                f"was started separately on each side ({here} here, {there} in the "
                f"file), so these are two records under one name. rename= brings "
                f"the file in as a project of its own, and note_merge joins two "
                f"records when that is what they are")
            return None
        if origin is None:
            self.conflicts.append(
                f"{kind}{row['seq']} is a different {what} on each side. Here: "
                f"{_head(held[''][body])}  File: {_head(row[body])}. The file does "
                f"not say which notebook wrote it -- a version before that was "
                f"carried wrote it -- so the two cannot be told apart; export it "
                f"again on that machine once it runs this version")
            return None
        if origin == self.s.name:
            self.conflicts.append(
                f"{kind}{row['seq']} was written, the file says, in a notebook named "
                f"{origin!r}, which is this notebook's own name -- and this notebook "
                f"has no such {what}. Two notebooks drew the same name")
            return None
        if origin in held:
            self.conflicts.append(
                f"{kind}{row['seq']}@{origin} is here already as a different {what}. "
                f"Here: {_head(held[origin][body])}  File: {_head(row[body])}")
            return None
        return origin

    def origin(self, table: str, have, incoming: dict) -> None:
        """Where a row here was written, learned from a file that says so:
        rows carried before files did are unknown until then. Once."""
        there = incoming.get("origin")
        if there is None or have["origin"] == there:
            return
        if have["origin"] is None:
            self.db.execute(f"UPDATE {table} SET origin=? WHERE id=?", (there, have["id"]))
            self.origins += 1
            return
        self.conflicts.append(
            f"{_lab(table[0].upper(), have)} was written in {have['origin']!r} by this "
            f"notebook's record, and in {there!r} by the file's")

    def questions(self, pid: int) -> dict[str, int]:
        ids = {r["ident"]: r["id"] for r in self.db.execute(
            "SELECT id, ident FROM questions WHERE project_id=?", (pid,))}
        ident_of = {v: k for k, v in ids.items()}
        for q in sorted(self.data["questions"], key=lambda q: (q["seq"], q["ident"])):
            have_id = ids.get(q["ident"])
            if have_id is None:
                qual = self._qual("Q", pid, q)
                if qual is None:
                    continue
                # A parent or a replaced question is always an earlier one --
                # it existed when this one was numbered -- so inserting in
                # number order has it already.
                cur = self.db.execute(
                    "INSERT INTO questions (project_id, seq, text, headline,"
                    " supersedes, parent, created_at, ident, origin, qual)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pid, q["seq"], q["text"], q.get("headline"),
                     ids.get(q["supersedes"]), ids.get(q.get("parent")),
                     q["created_at"], q["ident"], q.get("origin"), qual))
                ids[q["ident"]] = cur.lastrowid
                ident_of[cur.lastrowid] = q["ident"]
                self.count("questions", "questions", cur.lastrowid)
                self.carry("questions", cur.lastrowid, "made")
                if qual:
                    self.qualified.append(f"Q{q['seq']}@{qual}")
                continue
            have = self.db.execute("SELECT * FROM questions WHERE id=?",
                                   (have_id,)).fetchone()
            mine = {"text": have["text"], "created_at": have["created_at"],
                    "supersedes": ident_of.get(have["supersedes"]),
                    "parent": ident_of.get(have["parent"])}
            # A file written before questions could stand under one another
            # carries no `parent` key at all. Absent is not "no parent": read
            # that way, every question in an older file would disagree with
            # one that has since been placed in a tree here, and the whole
            # import would be refused over a field the file cannot speak to.
            mine["headline"] = have["headline"]
            made = Q_MADE + tuple(f for f in ("parent", "headline") if f in q)
            diff = [f for f in made if mine[f] != q[f]]
            if diff:
                self.conflicts.append(
                    f"{_lab('Q', have)} is a different question on each side "
                    f"({', '.join(diff)} differ). Here: {_head(have['text'])}  "
                    f"File: {_head(q['text'])}")
            self.origin("questions", have, q)
        for q in self.data["questions"]:
            if self.conflicts or q["ident"] not in ids:
                continue
            have = self.db.execute("SELECT * FROM questions WHERE id=?",
                                   (ids[q["ident"]],)).fetchone()
            label = _lab("Q", have)
            # The user's words go with the answering, as part of it -- and
            # are compared only when the file carries them: a file written
            # before they existed cannot speak to them.
            close = Q_CLOSE[1]
            said = q.get("answer_user_said")
            if said is not None:
                close += ("answer_user_said",)
                if (have["closed_at"] is not None and have["answer_user_said"] is None
                        and all(have[f] == q.get(f) for f in Q_CLOSE[1])):
                    # The same answering, carried here by an import older
                    # than the column: the words arrive now, NULL to value.
                    self.db.execute("UPDATE questions SET answer_user_said=? WHERE id=?",
                                    (said, have["id"]))
                    self.closed.append(f"{label}: the user's words endorsing "
                                       f"its answer")
                    have = self.db.execute("SELECT * FROM questions WHERE id=?",
                                           (have["id"],)).fetchone()
            if self.step(f"{label} {q['status']}", "questions", have, q,
                         close, Q_CLOSE[0], q, fatal=True):
                self.carry("questions", have["id"], "closed")
            if q["superseded_by"] is not None:
                want = ids.get(q["superseded_by"])
                have = self.db.execute("SELECT * FROM questions WHERE id=?",
                                       (have["id"],)).fetchone()
                if have["superseded_by"] is None:
                    self.db.execute("UPDATE questions SET superseded_by=? WHERE id=?",
                                    (want, have["id"]))
                    if ("questions", have["id"]) not in self.fresh:
                        self.closed.append(
                            f"{label} superseded by {self.s._q_label(want)}")
                elif have["superseded_by"] != want:
                    self.conflicts.append(
                        f"{label} was replaced by a different question on each side")
            self.cites("Q", have["id"], q.get("cites"))
            for ps in q["postscripts"]:
                self.postscript(label, have["id"], ps)
        return ids

    def postscript(self, label: str, qid: int, ps: dict) -> None:
        """One note on an answered question: added if it is not here, and if
        it is, the mark on the answer that an import older than the mark
        could not carry -- NULL to value, once."""
        mark = {f: ps.get(f) for f in ("answer_is", "user_said")}
        when = ps["created_at"][:10]
        if mark["answer_is"] is not None and mark["answer_is"] not in ANSWER_IS:
            # A notebook newer than this one. The note comes across; what it
            # says about the answer is not read as something it is not.
            self.not_carried.append(
                f"{label}'s note of {when}: answer_is={mark['answer_is']!r}, which "
                f"this notebook does not know -- the note is carried without it")
            mark = {"answer_is": None, "user_said": None}
        have = self.db.execute(
            "SELECT id, answer_is, user_said FROM postscripts WHERE question_id=?"
            " AND text=? AND created_at=?", (qid, ps["text"], ps["created_at"])).fetchone()
        if have is None:
            cur = self.db.execute(
                "INSERT INTO postscripts (question_id, text, headline, answer_is,"
                " user_said, created_at) VALUES (?,?,?,?,?,?)",
                (qid, ps["text"], ps.get("headline"), mark["answer_is"],
                 mark["user_said"], ps["created_at"]))
            self.count("postscripts")
            self.carry("postscripts", cur.lastrowid, "made")
            return
        fill = {f: v for f, v in mark.items() if v is not None and have[f] is None}
        clash = [f for f, v in mark.items()
                 if v is not None and have[f] is not None and have[f] != v]
        if clash:
            self.not_carried.append(
                f"{label}'s note of {when}: {', '.join(clash)} differ on each side "
                f"-- this notebook's is kept")
        elif fill:
            self.db.execute(f"UPDATE postscripts SET {', '.join(f'{f}=?' for f in fill)}"
                            f" WHERE id=?", list(fill.values()) + [have["id"]])
            self.closed.append(f"{label}'s note of {when}: it says the answer was "
                               f"{mark['answer_is'] or 'marked'}")

    def attempts(self, pid: int, qids: dict[str, int]) -> dict[str, int]:
        ids = {r["ident"]: r["id"] for r in self.db.execute(
            "SELECT id, ident FROM attempts WHERE project_id=?", (pid,))}
        ident_of = {v: k for k, v in ids.items()}
        q_ident = {v: k for k, v in qids.items()}
        for a in sorted(self.data["attempts"], key=lambda a: (a["seq"], a["ident"])):
            have_id = ids.get(a["ident"])
            if have_id is None:
                if a["question"] not in qids:
                    self.conflicts.append(f"A{a['seq']} is under a question the file "
                                          f"does not carry")
                    continue
                qual = self._qual("A", pid, a)
                if qual is None:
                    continue
                cur = self.db.execute(
                    "INSERT INTO attempts (project_id, question_id, seq, hypothesis,"
                    " headline,"
                    " why_now, prompted_by, measure, falsifier, apparatus, open_commit,"
                    " open_dirty, open_untracked, created_at, ident, origin, qual)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, qids[a["question"]], a["seq"], a["hypothesis"],
                     a.get("headline"), a["why_now"],
                     ids.get(a["prompted_by"]), a["measure"], a["falsifier"],
                     a["apparatus"], a["open_commit"], a["open_dirty"],
                     a["open_untracked"], a["created_at"], a["ident"],
                     a.get("origin"), qual))
                ids[a["ident"]] = cur.lastrowid
                ident_of[cur.lastrowid] = a["ident"]
                self.count("attempts", "attempts", cur.lastrowid)
                self.carry("attempts", cur.lastrowid, "made")
                if qual:
                    self.qualified.append(f"A{a['seq']}@{qual}")
                continue
            have = self.db.execute("SELECT * FROM attempts WHERE id=?",
                                   (have_id,)).fetchone()
            mine = {f: have[f] for f in A_MADE if f not in ("question", "prompted_by")}
            mine["question"] = q_ident.get(have["question_id"])
            mine["prompted_by"] = ident_of.get(have["prompted_by"])
            mine["headline"] = have["headline"]
            made = A_MADE + (("headline",) if "headline" in a else ())
            diff = [f for f in made if mine[f] != a.get(f)]
            if diff:
                self.conflicts.append(
                    f"{_lab('A', have)} is a different attempt on each side "
                    f"({', '.join(diff)} differ). Here: {_head(have['hypothesis'])}  "
                    f"File: {_head(a['hypothesis'])}")
            self.origin("attempts", have, a)
        if self.conflicts:
            return ids
        for a in self.data["attempts"]:
            have = self.db.execute("SELECT * FROM attempts WHERE id=?",
                                   (ids[a["ident"]],)).fetchone()
            if self.step(f"{_lab('A', have)} {a['verdict']}", "attempts", have, a,
                         A_CLOSE[1], A_CLOSE[0], a, fatal=True):
                self.carry("attempts", have["id"], "closed")
            self.cites("A", have["id"], a.get("cites"))
            for n in a["notes"]:
                if not self.db.execute(
                        "SELECT 1 FROM attempt_notes WHERE attempt_id=? AND text=?"
                        " AND created_at=?", (have["id"], n["text"], n["created_at"])
                        ).fetchone():
                    cur = self.db.execute(
                        "INSERT INTO attempt_notes (attempt_id, shown_by, text,"
                        " headline, created_at) VALUES (?,?,?,?,?)",
                        (have["id"], ids.get(n["shown_by"]), n["text"],
                         n.get("headline"), n["created_at"]))
                    self.count("attempt notes")
                    self.carry("attempt_notes", cur.lastrowid, "made")
        # One front per notebook, not per project: two machines each measure
        # under their own question, and that is the ordinary state now. What
        # is still wrong is ONE notebook open under two.
        fronts: dict = defaultdict(list)
        for r in self.db.execute(
                "SELECT a.*, q.id qid FROM attempts a JOIN questions q"
                " ON q.id=a.question_id WHERE a.project_id=? AND a.closed_at IS NULL"
                " ORDER BY a.seq", (pid,)).fetchall():
            fronts[r["origin"]].append(r)
        for where, opened in fronts.items():
            if len({r["qid"] for r in opened}) > 1:
                self.conflicts.append(
                    "this would leave " + ", ".join(
                        f"{_lab('A', r)} (under {self.s._q_label(r['qid'])})"
                        for r in opened)
                    + f" open at once in {where or 'an unnamed notebook'}, under more "
                      f"than one question, and one notebook has one front")
        return ids

    def cites(self, kind: str, node_id: int, carried) -> None:
        """Place what a carried result or answer rests on.

        The cited row may be in a project this notebook does not hold, or in
        one whose own file has not arrived yet, so the link is written
        whether or not it resolves here: the name and the cited row's
        identity are what the file carries, and the reader is told when it
        points at nothing here rather than at something else.
        """
        for c in carried or []:
            if self.db.execute(
                    "SELECT 1 FROM citations WHERE kind=? AND node_id=? AND"
                    " to_project=? AND to_kind=? AND to_seq=? AND to_created IS ?",
                    (kind, node_id, c["project"], c["kind"], c["seq"],
                     c["created_at"])).fetchone():
                continue
            table = "attempts" if c["kind"] == "A" else "questions"
            row = (self.db.execute(
                f"SELECT t.id FROM {table} t JOIN projects p ON p.id=t.project_id"
                f" WHERE p.name=? AND t.ident=?",
                (self.name(c["project"]), c["ident"])).fetchone() if c.get("ident")
                else self.db.execute(
                f"SELECT t.id FROM {table} t JOIN projects p ON p.id=t.project_id"
                f" WHERE p.name=? AND t.seq=? AND t.created_at=?",
                (self.name(c["project"]), c["seq"], c["created_at"])).fetchone())
            self.db.execute(
                "INSERT INTO citations (kind, node_id, to_project, to_kind, to_seq,"
                " to_created, to_id, role, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (kind, node_id, c["project"], c["kind"], c["seq"],
                 c["created_at"], row["id"] if row else None,
                 c.get("role", "supports"), c["cited_at"]))
            self.count("citations")
            if row is None:
                self.not_carried.append(
                    f"{c['project']}/{c['kind']}{c['seq']}, cited by "
                    f"{self._label_of_node(kind, node_id)}: the record it "
                    f"names is not in this notebook, so the citation is carried "
                    f"but cannot be read here")

    def _label_of_node(self, kind: str, node_id: int) -> str:
        table = "attempts" if kind == "A" else "questions"
        return _lab(kind, self.db.execute(f"SELECT seq, qual FROM {table} WHERE id=?",
                                          (node_id,)).fetchone())

    # requests and defects ---------------------------------------------

    def attempt_here(self, ref: Optional[dict]) -> Optional[int]:
        """The local attempt a cross-project reference names -- if this
        notebook holds that exact attempt, and not merely one with its label."""
        if ref is None:
            return None
        r = (self.db.execute(
            "SELECT a.id FROM attempts a JOIN projects p ON p.id=a.project_id"
            " WHERE p.name=? AND a.ident=?",
            (self.name(ref["project"]), ref["ident"])).fetchone() if ref.get("ident")
            else self.db.execute(
            "SELECT a.id FROM attempts a JOIN projects p ON p.id=a.project_id"
            " WHERE p.name=? AND a.seq=? AND a.created_at=?",
            (self.name(ref["project"]), ref["seq"], ref["created_at"])).fetchone())
        return r["id"] if r else None

    def local(self, kind: str, seq: int, row_ident: str):
        """This notebook's copy of a request or defect: same number, same
        contents. Another record holding the number is not it."""
        return next((r for r in self.s._rd_rows(kind, seq)
                     if self.s._ident_of(kind, r) == row_ident), None)

    def arrived(self, kind: str, have) -> None:
        """A request or defect inserted just now. Say so if its number was
        already held here: it prints qualified, and the other stays bare."""
        label = self.s._rd_label(kind, have)
        if label != f"{kind}{have['seq']}":
            self.qualified.append(label)

    def sides(self, kind: str, label: str, have, incoming: dict) -> None:
        """The same record, by its contents. Its two sides may still be named
        differently on each machine; this notebook's names stay."""
        for col, key in (R_SIDES if kind == "R" else D_SIDES):
            here, there = self.s._project_name(have[col]), self.name(incoming[key])
            if here != there:
                self.kept.append(
                    f"{label}'s {key}: {here!r} here, {incoming[key]!r} in the file. "
                    f"It is the same record -- what it was made with matches -- and "
                    f"rename= says when two names are one project")

    def crossing_notes(self, label: str, table: str, key: str, row_id: int,
                       notes: list[dict]) -> None:
        for n in notes:
            by = self.party(n["written_by"])
            if self.db.execute(
                    f"SELECT 1 FROM {table} WHERE {key}=? AND written_by=? AND text=?"
                    f" AND created_at=?", (row_id, by, n["text"], n["created_at"])
                    ).fetchone():
                continue
            shown = self.attempt_here(n["shown_by"])
            if n["shown_by"] is not None and shown is None:
                # Carried without it, it would print as INTERPRETATION -- a
                # claim that nothing measured it, which is false.
                self.not_carried.append(
                    f"a note on {label} by {self.name(n['written_by'])}: the attempt "
                    f"it cites, {self.name(n['shown_by']['project'])} "
                    f"A{n['shown_by']['seq']}, is not in this notebook")
                continue
            cur = self.db.execute(
                f"INSERT INTO {table} ({key}, written_by, shown_by, text, created_at)"
                f" VALUES (?,?,?,?,?)", (row_id, by, shown, n["text"], n["created_at"]))
            self.count("notes on requests and defects")
            self.carry(table, cur.lastrowid, "made")

    def requests(self) -> None:
        for r in sorted(self.data["requests"], key=lambda r: (r["seq"], ident("R", r))):
            rid = ident("R", r)
            have = self.local("R", r["seq"], rid)
            if have is None:
                cur = self.db.execute(
                    "INSERT INTO requests (seq, ident, asked_by, owner_id, wanted,"
                    " because, context, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (r["seq"], rid, self.party(r["asked_by"]), self.party(r["owner"]),
                     r["wanted"], r["because"], r["context"], r["created_at"]))
                have = self.db.execute("SELECT * FROM requests WHERE id=?",
                                       (cur.lastrowid,)).fetchone()
                self.count("requests", "requests", cur.lastrowid)
                self.carry("requests", have["id"], "made")
                self.arrived("R", have)
            label = self.s._rd_label("R", have)
            if ("requests", have["id"]) not in self.fresh:
                self.sides("R", label, have, r)
            if self.step(f"{label} {r['decision']}", "requests", have, r,
                         R_CLOSE[1], R_CLOSE[0], r, fatal=False):
                self.carry("requests", have["id"], "closed")
            self.crossing_notes(label, "request_notes", "request_id", have["id"],
                                r["notes"])

    def superseded(self, d: dict, in_file: dict[int, list[str]]) -> Optional[int]:
        """The defect a re-filed one supersedes, as a row here. By number and
        hash; a file written before the hash was carried beside the number
        names it by number alone, and its numbers were unique."""
        seq = d.get("supersedes")
        if seq is None:
            return None
        sid = d.get("supersedes_ident")
        if sid is None:
            if len(in_file.get(seq, [])) != 1:
                return None
            sid = in_file[seq][0]
        row = self.local("D", seq, sid)
        return row["id"] if row is not None else None

    def defects(self) -> None:
        in_file: dict[int, list[str]] = defaultdict(list)
        for d in self.data["defects"]:
            in_file[d["seq"]].append(ident("D", d))
        for d in sorted(self.data["defects"], key=lambda d: (d["seq"], ident("D", d))):
            did = ident("D", d)
            have = self.local("D", d["seq"], did)
            if have is None:
                aid = self.attempt_here(d["attempt"])
                rid = self.attempt_here(d.get("reading_in"))
                context = d["context"]
                if d["attempt"] is not None and aid is None:
                    a = d["attempt"]
                    context = (f"{self.name(a['project'])} A{a['seq']}  "
                               f"{a['hypothesis']}  (the measurement this stopped is "
                               f"in the notebook this was carried from, not this one)")
                if d.get("reading_in") is not None and rid is None:
                    a = d["reading_in"]
                    context = (f"{self.name(a['project'])} A{a['seq']}  "
                               f"{a['hypothesis']}  (nothing was stopped: a reading "
                               f"inside it was false. It is in the notebook this was "
                               f"carried from, not this one)")
                cur = self.db.execute(
                    "INSERT INTO defects (seq, ident, reported_by, owner_id, attempt_id,"
                    " reading_in, invocation, observed, needed, supersedes, context,"
                    " seen_commit, seen_dirty, seen_untracked, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (d["seq"], did, self.party(d["reported_by"]), self.party(d["owner"]),
                     aid, rid, d["invocation"], d["observed"], d["needed"],
                     self.superseded(d, in_file), context, d["seen_commit"],
                     d["seen_dirty"], d["seen_untracked"], d["created_at"]))
                have = self.db.execute("SELECT * FROM defects WHERE id=?",
                                       (cur.lastrowid,)).fetchone()
                self.count("defects", "defects", cur.lastrowid)
                self.carry("defects", have["id"], "made")
                self.arrived("D", have)
            label = self.s._rd_label("D", have)
            if ("defects", have["id"]) not in self.fresh:
                self.sides("D", label, have, d)
            values = dict(d)
            if d["asked_by"] is not None:
                values["asked_by"] = self.party(d["asked_by"])
            for key, fields in D_STEPS:
                have = self.db.execute("SELECT * FROM defects WHERE id=?",
                                       (have["id"],)).fetchone()
                if self.step(f"{label} {key.replace('_at', '')}", "defects", have, d,
                             fields, key, values, fatal=False):
                    self.carry("defects", have["id"], D_EVENT[key])
            self.crossing_notes(label, "defect_notes", "defect_id", have["id"],
                                d["notes"])

    # all of it ----------------------------------------------------------

    def run(self) -> None:
        pid = self.project()
        self.absorbed(self.name(self.data["project"]["name"]))
        qids = self.questions(pid)
        if not self.conflicts:
            self.attempts(pid, qids)
        if self.conflicts:
            raise _Disagree(self.conflicts)
        self.requests()
        self.defects()
        # The position is a pointer, and each machine moves its own. Take the
        # file's only when this notebook has nothing the file lacks -- then
        # the file is simply further along. Otherwise both moved, and the
        # one here is the one somebody here last stood on.
        name = self.name(self.data["project"]["name"])
        mine = snapshot(self.s, name)
        theirs = self.data["project"]["current_question"]
        if (mine["questions"] == self.data["questions"]
                and mine["attempts"] == self.data["attempts"]):
            want = qids.get(theirs)
            if want is not None:
                self.db.execute("UPDATE projects SET current_question=? WHERE id=?",
                                (want, pid))
        elif theirs is not None and theirs != mine["project"]["current_question"]:
            self.kept.append("the position: this notebook has records the file "
                             "does not, so it is further along in some way, and "
                             "note_export here brings the file up to date")
        for twin, there in sorted(self.twins.items()):
            self.beside.append(
                f"{twin!r} is named in the file's requests or defects and became a "
                f"blank card here, beside {there!r}, which differs from it only in "
                f"case. rename={{{twin!r}: {there!r}}} reads it as that one")
        # A name the caller said to read differently is recorded, so the next
        # import of the other machine's files reads it the same way without
        # being told again.
        for frm, to in sorted(self.applied.items()):
            row = self.s._project_row(to, required=False)
            if frm not in self.aliases and row is not None:
                self.db.execute(
                    "INSERT INTO aliases (name, project_id, import_id) VALUES (?,?,?)",
                    (frm, row["id"], self.import_row()))


class _Disagree(Exception):
    pass


def _head(text: Optional[str], width: int = 60) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line if len(line) <= width else line[:width] + "..."


def _where(store: Store, tbl: str, row) -> str:
    """Where a carried text sits, in labels a reader can pass to note_open."""
    lab = lambda t, i: store.db.execute(f"SELECT seq, qual FROM {t} WHERE id=?",
                                        (i,)).fetchone()
    rd = lambda kind, i: store._rd_label(kind, store.db.execute(
        f"SELECT * FROM {'requests' if kind == 'R' else 'defects'} WHERE id=?",
        (i,)).fetchone())
    return {"questions": lambda: _lab("Q", row),
            "postscripts": lambda: f"{_lab('Q', lab('questions', row['question_id']))} postscript",
            "attempts": lambda: _lab("A", row),
            "attempt_notes": lambda: f"{_lab('A', lab('attempts', row['attempt_id']))} note",
            "requests": lambda: store._rd_label("R", row),
            "request_notes": lambda: f"{rd('R', row['request_id'])} note",
            "defects": lambda: store._rd_label("D", row),
            "defect_notes": lambda: f"{rd('D', row['defect_id'])} note"}[tbl]()


def _misreadings(store: Store, m: _Merge) -> dict:
    """Which text this import carried in cites a bare label that, here, bare,
    is a different record -- and which record it meant.

    Worked out the way note_open does it, so what the import reports is what
    every later reading shows. Nothing is rewritten: "D4" is as often a part
    as a defect in a circuit record, so a substitution would corrupt
    designators as surely as it fixed citations. Pad references ("D4.1") are
    skipped, since no label is written that way; the rest are read by whoever
    imports."""
    if m.import_id is None:
        return {}
    now: dict[tuple[str, int], set[str]] = defaultdict(set)
    before: dict[tuple[str, int], set[str]] = defaultdict(set)
    for r in store.db.execute("SELECT tbl, row_id, event, import_id FROM carried"):
        (now if r["import_id"] == m.import_id else before)[(r["tbl"], r["row_id"])].add(
            r["event"])
    # Text an EARLIER import carried can change meaning now: it cited a
    # number whose record had not arrived yet. Trace-from-photos' D4 and R19
    # cite its R16, which only cadbridge's file carries -- so whichever file
    # came second, its import is the one that can say so.
    numbers = set()
    for t, i in m.fresh:
        if t in ("requests", "defects"):
            seq = store.db.execute(f"SELECT seq FROM {t} WHERE id=?", (i,)).fetchone()["seq"]
            numbers.add(("R" if t == "requests" else "D", seq))
    passages = [(k, evs, None) for k, evs in sorted(now.items())]
    if numbers:
        passages += [(k, evs, numbers) for k, evs in sorted(before.items()) if k not in now]
    found: dict[str, dict] = {}
    for (tbl, rid), evs, only in passages:
        row = store.db.execute(f"SELECT * FROM {tbl} WHERE id=?", (rid,)).fetchone()
        per: dict[tuple[str, str], list[str]] = defaultdict(list)
        for f, kind, seq, text, meant in store._misread(tbl, row, evs):
            if only is None or (kind, seq) in only:
                per[(f"{kind}{seq}", f)].append(text)
        for (label, f), texts in per.items():
            kind, seq = label[0], int(label[1:])
            entry = found.setdefault(label, {
                "means here": " | ".join(store._rd_line(kind, r) for r in
                                         store._meant_elsewhere(kind, seq)),
                "bare here": store._rd_line(kind, store._rd_rows(kind, seq)[0]),
                "named in": []})
            text = texts[0]
            hit = re.search(rf"(?<![A-Za-z0-9_]){label}(?![0-9@]|\.[0-9])", text)
            at = (hit.start(), hit.end()) if hit else (0, 0)
            snip = " ".join(text[max(0, at[0] - 30):at[1] + 40].split())
            where = _where(store, tbl, row)
            where += "" if tbl.endswith(("notes", "postscripts")) else f" {f}"
            where += "" if only is None else " (carried by an earlier import)"
            entry["named in"].append(f"{where}: ...{snip}..."
                                     + (f"  (+{len(texts) - 1} more here)"
                                        if len(texts) > 1 else ""))
    return dict(sorted(found.items(), key=lambda kv: (kv[0][0], int(kv[0][1:]))))


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise NoteError(f"no file at {str(path)!r}") from None
    except json.JSONDecodeError as e:
        raise NoteError(f"{str(path)!r} is not a notebook file: {e}") from None
    if not isinstance(data, dict) or data.get("format") not in (FORMAT, FORMAT_V1):
        raise NoteError(f"{str(path)!r} is not a notebook file this version reads "
                        f"(format {data.get('format') if isinstance(data, dict) else None!r}, "
                        f"expected {FORMAT!r})")
    return _upgraded(data) if data["format"] == FORMAT_V1 else data


def _upgraded(data: dict) -> dict:
    """A /1 file in /2's shape. Its references are numbers, which were
    unique in the file, so each becomes the ident of the row it named. It
    does not say where its rows were written, and that stays unknown."""
    qs = {q["seq"]: ident("Q", q) for q in data["questions"]}
    at = {a["seq"]: ident("A", a) for a in data["attempts"]}
    ref = lambda table, seq: None if seq is None else table.get(seq)
    for q in data["questions"]:
        q["ident"], q["origin"] = qs[q["seq"]], None
        for k in ("supersedes", "superseded_by", "parent"):
            if k in q:
                q[k] = ref(qs, q[k])
    for a in data["attempts"]:
        a["ident"], a["origin"] = at[a["seq"]], None
        a["question"] = ref(qs, a["question"])
        a["prompted_by"] = ref(at, a["prompted_by"])
        for n in a["notes"]:
            n["shown_by"] = ref(at, n["shown_by"])
    data["project"]["current_question"] = ref(qs, data["project"]["current_question"])
    data["format"] = FORMAT
    return data


def _names_in(data: dict) -> set[str]:
    """Every project name a file writes: its own, and each side it records."""
    names = {data["project"]["name"]}
    refs = lambda *xs: {x["project"] for x in xs if x}
    for r in data["requests"]:
        names |= {r["asked_by"], r["owner"]}
        for n in r["notes"]:
            names |= {n["written_by"]} | refs(n["shown_by"])
    for d in data["defects"]:
        names |= {d["reported_by"], d["owner"]} | refs(d["attempt"], d.get("reading_in"))
        names |= {d["asked_by"]} if d["asked_by"] else set()
        for n in d["notes"]:
            names |= {n["written_by"]} | refs(n["shown_by"])
    return names


def _checked_rename(store: Store, rename: Optional[dict], datas: dict) -> dict[str, str]:
    """rename= as given, refused where it cannot mean what it says.

    It reads a project name the other notebook writes as a project here: its
    own card, and every request and defect that names it as a side. What
    joins the two is still what the rest of the import checks -- a question
    or attempt that differs is refused at its label, as for any file -- so a
    blank card, which has nothing to renumber, is what this can join."""
    out: dict[str, str] = {}
    known = set().union(*(_names_in(d) for d in datas.values())) if datas else set()
    aliases = {r["name"]: r["project"] for r in store.db.execute(
        "SELECT a.name, p.name project FROM aliases a JOIN projects p ON p.id=a.project_id")}
    for frm, to in (rename or {}).items():
        if not isinstance(frm, str) or not isinstance(to, str) or not frm or not to.strip():
            raise NoteError(f"rename= maps a name in the file to a project here, both "
                            f"non-empty; got {frm!r}: {to!r}")
        to = to.strip()
        if frm == to:
            continue
        if frm not in known:
            raise NoteError(
                f"rename= names {frm!r}, which no record in "
                f"{', '.join(repr(str(p.name)) for p in datas) or 'the file'} "
                f"mentions. The projects there are: {sorted(known)}")
        if store._project_row(frm, required=False) is not None:
            raise NoteError(
                f"{frm!r} is already a project here. Reading it as {to!r} from now "
                f"on would split one name between two projects: what is filed under "
                f"{frm!r} here stays there, since nothing here is moved.")
        if aliases.get(frm, to) != to:
            raise NoteError(
                f"{frm!r} is already read as {aliases[frm]!r} here -- an earlier "
                f"import was told so, and that stays. It cannot also be {to!r}.")
        out[frm] = to
    return out


@contextmanager
def _trial(store: Store):
    """A merge that is looked at and then thrown away."""
    store.db.execute("BEGIN IMMEDIATE")
    try:
        yield
    finally:
        store.db.execute("ROLLBACK")


def _refusal(path: Path, name: str, conflicts: list[str],
             outcome: str = "so nothing was imported") -> str:
    return (f"{str(path)!r} and this notebook disagree about {name!r}, {outcome}:"
            f"\n  " + "\n  ".join(conflicts) + "\n"
            f"Both machines added to it without importing the other's work first. "
            f"Labels are cited inside other records, so neither side is renumbered "
            f"to fit. Both records are intact; which one continues is a decision "
            f"for whoever owns the project, not for the import.")


# -- the two calls -------------------------------------------------------

def _merge_one(store: Store, path: Path, data: dict, repo: str, dry_run: bool,
               rename: dict[str, str]) -> dict:
    """One file, inside a transaction the caller holds. Everything it
    reports is read inside it: in a dry run the rows are gone after."""
    m = _Merge(store, data, repo, rename, str(path))
    try:
        m.run()
    except _Disagree as e:
        raise NoteError(_refusal(
            path, data["project"]["name"], e.args[0],
            "so this import would be refused (nothing was written)" if dry_run
            else "so nothing was imported")) from None
    name = m.name(data["project"]["name"])
    out: dict = {}
    if dry_run:
        out["DRY RUN"] = ("nothing was written. This is what note_import would "
                          "do with this file, found by doing it and rolling back")
    out.update({"file": str(path), "project": name})
    if m.applied:
        out["read as"] = [
            f"{frm!r} as {to!r}" + (" (recorded here earlier)" if frm in m.aliases
                                    else " -- recorded, so later imports read it "
                                         "the same way without being told")
            for frm, to in sorted(m.applied.items())]
    if m.joined:
        out["would merge" if dry_run else "merged"] = m.joined
    if m.beside:
        out["would arrive beside" if dry_run else "arrived beside"] = m.beside
    if not m.changed():
        out["result"] = "nothing new -- this notebook already had all of it"
    else:
        out["would add" if dry_run else "added"] = ", ".join(
            f"{n} {k}" for k, n in m.added.items()) or "no rows"
        if m.closed:
            out["would close or settle" if dry_run else "closed or settled since"] = m.closed
    if m.qualified:
        out["numbers already held here"] = {
            "read this": "each of these arrived under its own number, which a "
                         "record here already holds. Neither is renumbered: the "
                         "one here keeps the bare label, and this one prints, "
                         "beside the number, the notebook that wrote it (a "
                         "question or attempt) or the hash of what it was made "
                         "with (a request or defect)",
            "labels": ", ".join(m.qualified)}
    if m.origins:
        out["where written"] = (f"{m.origins} question(s) and attempt(s) here were "
                                f"carried in before files said which notebook wrote "
                                f"them; this one does, and it is recorded")
    if m.not_carried:
        out["would leave behind" if dry_run else "not carried"] = m.not_carried
    cites = _misreadings(store, m)
    if cites:
        out["carried text whose bare labels are other records here"] = {
            "read this": "each passage below was written in another notebook, "
                         "where a bare label named that notebook's own record. "
                         "Here the same bare label is a different record; the "
                         "one meant is named beside it, and note_open on the "
                         "passage says so wherever it is read. Nothing is "
                         "rewritten. They are string matches, and in a circuit "
                         "record R1 or D4 is as often a part as a request or "
                         "defect -- which are citations is for you to read",
            **cites}
    if m.kept:
        out["kept this notebook's"] = m.kept
    cq = store._current_question(store._project_row(name)["id"])
    out["position"] = f"{_lab('Q', cq)}  {_head(cq['text'])}" if cq else "no question yet"
    return out


def import_file(store: Store, path: str | Path, dry_run: bool = False,
                rename: Optional[dict[str, str]] = None) -> dict:
    """Merge one file. With dry_run the same merge runs and is rolled back,
    so what it reports is what the import would do, not a forecast of it."""
    path = Path(path).expanduser().resolve()
    data = _load(path)
    names = _checked_rename(store, rename, {path: data})
    found = rig.is_repo(path.parent)          # read before the write lock
    with (_trial(store) if dry_run else store._writing()):
        return _merge_one(store, path, data, str(found) if found else "", dry_run, names)


def import_path(store: Store, path: str, dry_run: bool = False,
                rename: Optional[dict[str, str]] = None) -> dict:
    """A file, or a repository root: every project file it carries.

    A dry run of several files is one merge rolled back at the end, file
    after file as the import would do them -- so the second file's report
    already sees what the first one added. Rolled back one at a time, the
    second was reported against a notebook the import would never meet."""
    p = Path(path.strip()).expanduser()
    if not p.is_dir():
        return import_file(store, p, dry_run, rename)
    where = p if p.name == SHARE_DIR else p / SHARE_DIR
    files = sorted(f.resolve() for f in where.glob("*.json")) if where.is_dir() else []
    if not files:
        raise NoteError(f"no {SHARE_DIR}/*.json under {str(p)!r}. note_export "
                        f"on the other machine writes one there.")
    loaded, results = {}, {}
    for f in files:
        try:
            loaded[f] = _load(f)
        except NoteError as e:
            results[f] = {"file": str(f), "REFUSED": str(e)}
    names = _checked_rename(store, rename, loaded)
    repos = {f: rig.is_repo(f.parent) for f in loaded}      # before the lock
    one = lambda f: _merge_one(store, f, loaded[f], str(repos[f]) if repos[f] else "",
                               dry_run, names)
    if dry_run:
        with _trial(store):
            for f in loaded:
                store.db.execute("SAVEPOINT one_file")
                try:
                    results[f] = one(f)
                except NoteError as e:
                    store.db.execute("ROLLBACK TO one_file")
                    results[f] = {"file": str(f), "REFUSED": str(e)}
                store.db.execute("RELEASE one_file")
    else:
        for f in loaded:
            try:
                with store._writing():
                    results[f] = one(f)
            except NoteError as e:
                results[f] = {"file": str(f), "REFUSED": str(e)}
    return {"would import" if dry_run else "imported": [results[f] for f in files]}


def export_project(store: Store, project: str, path: Optional[str] = None) -> dict:
    row = store._project_row(project)
    if row["name"] != project.strip():
        raise NoteError(
            f"{project!r} was merged into {row['name']!r}, and its record went "
            f"with it. note_export({row['name']!r}) writes that one -- and "
            f"carries the merge, so the other notebook makes it too.")
    dest = target(store, project, path)
    # Two projects whose names differ only in case get two file names that a
    # Linux checkout holds side by side and a Windows or macOS one cannot:
    # git there checks one out over the other, and whichever loses is a whole
    # record gone from the machine it was carried to.
    over = None
    if dest.parent.is_dir():
        for f in dest.parent.iterdir():
            if f.name != dest.name and f.name.lower() == dest.name.lower():
                # pcbrouter.json beside PcbRouter.json, when pcbrouter was
                # merged into PcbRouter: that file is this record's older
                # half, and the merged record goes over it, under its name --
                # the import reads the project from inside, not from the name.
                try:
                    was = _load(f)["project"]["name"]
                except NoteError:
                    was = None
                if was is not None and was != project and store._project_row(
                        was, required=False) is not None and                         store._project_row(was)["name"] == project:
                    dest, over = f, was
                    continue
                raise NoteError(
                    f"{str(f)!r} is already there, and its name differs from "
                    f"{dest.name!r} only in case. A Windows or macOS checkout "
                    f"cannot hold both -- one is checked out over the other. "
                    f"Pass path= with a file name of its own, such as "
                    f"{dest.stem}-<something>.json in the same directory; "
                    f"note_import reads the project from inside the file, "
                    f"not from its name.")
    with _trial(store):
        # Before overwriting it, read what it carries. A file holding records
        # this notebook lacks is the other machine's work on its way here;
        # replacing it would take that work back out of transit, and the
        # next write here would collide with it.
        if dest.is_file():
            there = _load(dest)
            if there["project"]["name"] not in (project, over):
                raise NoteError(
                    f"{str(dest)!r} is {there['project']['name']!r}'s record, not "
                    f"{project!r}'s. Pass a different path=.")
            behind = _Merge(store, there, "")
            try:
                behind.run()
            except _Disagree as e:
                raise NoteError(
                    _refusal(dest, project, e.args[0]).replace(
                        "so nothing was imported", "so it was not overwritten"))
            if behind.changed():
                raise NoteError(
                    f"{str(dest)!r} carries records this notebook does not have "
                    f"yet ({', '.join(behind.closed[:3] + [f'{n} {k}' for k, n in behind.added.items()])}). "
                    f"That is the other machine's work on its way here. "
                    f"note_import it first, then export.")
        data = snapshot(store, project)
        opens = store._open_attempts(store._project_row(project)["id"])
    text = render(data)
    unchanged = dest.is_file() and dest.read_text(encoding="utf-8") == text
    if not unchanged:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    out = {"project": project, "file": str(dest),
           "wrote": ("nothing -- the file already says exactly this" if unchanged
                     else f"{len(data['questions'])} questions, "
                          f"{len(data['attempts'])} attempts, "
                          f"{len(data['requests'])} requests, "
                          f"{len(data['defects'])} defects"),
           "next": "carry the file however the code travels; on the other "
                   "machine, note_import(path) before writing anything to "
                   "this project"}
    if over:
        out["written over"] = (f"{dest.name} held {over!r}, which was merged into "
                               f"{project!r}; the merged record replaces it under "
                               f"that file name, since a checkout on Windows or macOS "
                               f"cannot hold two names that differ only in case")
    if opens:
        one = len(opens) == 1
        out[", ".join(_lab("A", a) for a in opens) + (" is open" if one else " are open")] = (
            f"if this file is committed before {'it closes' if one else 'they close'}, "
            f"HEAD moves under {'it' if one else 'them'}, and "
            f"{'it' if one else 'each'} will close against a different commit "
            f"than it opened on -- the record will say the code moved. Commit "
            f"the file after {'it closes' if one else 'they close'}, or read that "
            f"line knowing why.")
    return out


# -- by hand --------------------------------------------------------------

def _pair(text: str) -> tuple[str, str]:
    frm, sep, to = text.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"expected NAME_IN_FILE=PROJECT_HERE, got {text!r}")
    return frm, to


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sainpost.share",
                                 description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="write a project's record into its repository")
    e.add_argument("project")
    e.add_argument("path", nargs="?", default="")
    i = sub.add_parser("import", help="merge a project file, or every one a repository carries")
    i.add_argument("path")
    i.add_argument("--dry-run", action="store_true",
                   help="say what the import would do, and write nothing")
    i.add_argument("--rename", action="append", type=_pair, default=[],
                   metavar="NAME_IN_FILE=PROJECT_HERE",
                   help="read a project the file names as a project here; repeatable")
    args = ap.parse_args(argv)
    store = Store()
    try:
        out = (export_project(store, args.project, args.path or None)
               if args.cmd == "export"
               else import_path(store, args.path, args.dry_run, dict(args.rename)))
    except NoteError as err:
        print(f"REFUSED: {err}", file=sys.stderr)
        return 1
    finally:
        store.close()
    # A Japanese console is cp932; replace what it cannot show rather than die.
    sys.stdout.reconfigure(errors="replace")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

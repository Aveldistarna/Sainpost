"""The notebook as a tree a person can look at.

Every other view here is text sized for a model's context: one line per
node, bodies one call away, a map in place of a trail too big for one reply.
A person arrives with the same two questions an agent does -- where is the
work, and what has already been ruled out -- and reads the answer faster as
a picture: questions under what they serve, attempts under their question,
each coloured by its verdict, and every body one click away.

    python -m sainpost.view                   # serve it on localhost
    python -m sainpost.view --out tree.html   # one self-contained file

Reads only. The notebook is opened with Store.read_only, so SQLite itself
refuses every write, and what is shown comes from the same trail() and
open() the tools run -- a second reading of the record, written here, would
be a second record that could disagree with the first.

Served, each reload reads the notebook again, so a page left open beside a
working agent shows what it wrote. The server answers 127.0.0.1 only: the
notebook is every project on the machine, including other people's work in
flight. The written file carries the same, so it is not a thing to publish.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

# Run as a file (`python sainpost/view.py`) as well as a module, the way
# launch.py runs server.py: a person reaches for the file they can see.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sainpost.store import NoteError, Store  # noqa: E402

#: The label a request or defect line starts with: R6, or R6@3fa2c1.
_RD_LABEL = re.compile(r"^([RD]\d+(?:@[0-9a-f]+)?)\b")


def snapshot(store: Store) -> dict:
    """Every project's tree, with the body of every node in it."""
    projects = []
    for p in store.projects():
        name = p["project"]
        trail = store.trail(name)
        attempts = [a for q in trail["trail"] for a in q["attempts"]]
        labels = [q["question"] for q in trail["trail"]] + [a["attempt"] for a in attempts]
        for line in (p["blocked_on"] + p["waiting_on_you"]
                     + [a.get("defect") or "" for a in attempts]):
            m = _RD_LABEL.match(line)
            if m and m.group(1) not in labels:
                labels.append(m.group(1))
        # open() returns one node per label, in the order asked.
        nodes = store.open(name, labels)["nodes"] if labels else []
        cur = p["current_question"]
        projects.append({
            **p,
            "now": cur.split()[0] if cur else None,
            "trail": trail,
            "bodies": dict(zip(labels, nodes)),
        })
    return {"notebook": str(store.path),
            "read_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "projects": projects}


def read(path: Optional[Path | str] = None) -> dict:
    store = Store.read_only(path)
    try:
        return snapshot(store)
    finally:
        store.close()


def render(snap: dict, live: bool = False) -> str:
    """One HTML page, everything inline: no network, nothing to install."""
    data = json.dumps({**snap, "live": live}, ensure_ascii=False, default=str)
    # Inside a <script> element only "</script" and "<!--" end or bend it;
    # escaping every <, > and & keeps the JSON valid and ends that for good.
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return _PAGE.replace("__DATA__", data)


def _refused(message: str) -> str:
    text = (message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return ("<!doctype html><meta charset='utf-8'><title>Sainpost Tree</title>"
            "<body style='font:15px system-ui;padding:2em'><h1>Could not read the "
            f"notebook</h1><pre style='white-space:pre-wrap'>{text}</pre></body>")


class _Handler(BaseHTTPRequestHandler):
    notebook: Optional[Path] = None
    port: int = 0

    def do_GET(self) -> None:                                   # noqa: N802
        # A page on any site can make the browser ask a name that resolves
        # here; the Host header is what says the browser was pointed at this.
        host = (self.headers.get("Host") or "").lower()
        if host not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            self.send_error(403)
            return
        if self.path.split("?")[0] not in ("/", "/index.html"):
            self.send_error(404)
            return
        try:
            status, page = 200, render(read(self.notebook), live=True)
        except (NoteError, OSError, ValueError) as e:
            status, page = 500, _refused(str(e))
        except Exception as e:                                  # noqa: BLE001
            status, page = 500, _refused(f"{type(e).__name__}: {e}")
        body = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def serve(notebook: Optional[Path], port: int, browser: bool) -> None:
    read(notebook)                        # a notebook that cannot be read says so now
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    except OSError:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    _Handler.notebook = notebook
    _Handler.port = httpd.server_address[1]
    url = f"http://127.0.0.1:{_Handler.port}/"
    print(f"Sainpost tree at {url}  (reads only; Ctrl+C stops it)",
          file=sys.stderr, flush=True)
    if browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sainpost.view",
                                 description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", metavar="FILE",
                    help="write one self-contained HTML file and exit")
    ap.add_argument("--port", type=int, default=8765,
                    help="where to serve (default 8765; taken, any free one)")
    ap.add_argument("--no-browser", action="store_true",
                    help="serve without opening a browser")
    ap.add_argument("--db", metavar="PATH",
                    help="the notebook to read (default: this machine's)")
    args = ap.parse_args(argv)
    notebook = Path(args.db) if args.db else None
    try:
        if args.out:
            out = Path(args.out)
            out.write_text(render(read(notebook)), encoding="utf-8", newline="\n")
            print(out.resolve())
        else:
            serve(notebook, args.port, not args.no_browser)
    except NoteError as err:
        print(f"REFUSED: {err}", file=sys.stderr)
        return 1
    return 0


_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sainpost Tree</title>
<style>
:root {
  --bg: #f4f5f7; --panel: #ffffff; --ink: #1c2230; --muted: #626b7c;
  --faint: #8b93a3; --line: #dde1e7; --edge: #a3acba; --accent: #2f5fd0;
  --hover: #eef2fb; --sel: #2f5fd0; --now: #d97706; --hit: #fff1b8;
  --CONFIRMED: #1f8a4c; --FALSIFIED: #cc3b3b; --INCONCLUSIVE: #b7791f;
  --ABANDONED: #7d8594; --BLOCKED: #8446b0; --OPEN: #2f5fd0;
  --interp-bg: #fff7e0; --interp-ink: #7a5a00; --warn-bg: #fdecec; --warn-ink: #9b2c2c;
  --code: #f1f3f6;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171c; --panel: #1c2027; --ink: #e5e8ee; --muted: #a0a8b6;
    --faint: #7c8595; --line: #2e343e; --edge: #56606f; --accent: #7aa2ff;
    --hover: #232a36; --sel: #7aa2ff; --now: #f0a53a; --hit: #4a3f12;
    --CONFIRMED: #3fb872; --FALSIFIED: #f06a6a; --INCONCLUSIVE: #e0a93b;
    --ABANDONED: #8d96a6; --BLOCKED: #b17ae0; --OPEN: #7aa2ff;
    --interp-bg: #2f2812; --interp-ink: #f0d58a; --warn-bg: #3a1c1c; --warn-ink: #ffb4b4;
    --code: #232833;
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; }
body { background: var(--bg); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", "Hiragino Sans", "Yu Gothic UI", "Meiryo", sans-serif;
  display: grid; grid-template-rows: auto 1fr; overflow: hidden; }
button, input { font: inherit; color: inherit; }
header { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px;
  padding: 8px 14px; background: var(--panel); border-bottom: 1px solid var(--line); }
header h1 { font-size: 15px; margin: 0; letter-spacing: .02em; }
header .src { color: var(--faint); font-size: 12px; }
header .grow { flex: 1; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 11px; color: var(--muted); }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; }
.tools { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.btn { border: 1px solid var(--line); background: var(--panel); border-radius: 6px; padding: 3px 9px; cursor: pointer; }
.btn:hover { background: var(--hover); }
.tools label { font-size: 12px; color: var(--muted); display: flex; gap: 4px; align-items: center; cursor: pointer; }
#q { border: 1px solid var(--line); background: var(--bg); border-radius: 6px; padding: 3px 8px; width: 200px; }
#hits { font-size: 12px; color: var(--muted); min-width: 4em; }

main { display: grid; grid-template-columns: 250px 1fr 420px; min-height: 0; }
#side { border-right: 1px solid var(--line); background: var(--panel); overflow: auto; }
#side h2, #detail h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--faint); margin: 12px 14px 6px; }
.proj { padding: 8px 14px; cursor: pointer; border-left: 3px solid transparent; }
.proj:hover { background: var(--hover); }
.proj.on { background: var(--hover); border-left-color: var(--accent); }
.proj .nm { font-weight: 600; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.proj .ct { font-size: 12px; color: var(--muted); }
.proj.empty { opacity: .55; }
.tag { font-size: 10px; font-weight: 600; border-radius: 3px; padding: 0 5px; line-height: 16px; letter-spacing: .03em; }
.tag.open { background: var(--OPEN); color: #fff; }
.tag.blocked { background: var(--BLOCKED); color: #fff; }
.tag.waiting { border: 1px solid var(--muted); color: var(--muted); }
.vbar { display: flex; height: 5px; border-radius: 3px; overflow: hidden; background: var(--line); margin-top: 4px; }
.vbar span { display: block; height: 100%; }

#canvas { position: relative; overflow: auto; cursor: grab; }
#canvas.drag { cursor: grabbing; user-select: none; }
#sizer { position: relative; }
#stage { position: absolute; left: 0; top: 0; transform-origin: 0 0; }
#edges { position: absolute; left: 0; top: 0; overflow: visible; pointer-events: none; }
.e { fill: none; stroke: var(--edge); stroke-width: 1.4; }
.e.sup { stroke: var(--muted); stroke-dasharray: 5 4; }
.e.pb { stroke: var(--accent); stroke-width: 1.2; stroke-dasharray: 2 3; opacity: .55; }
.e.pb.hot { opacity: 1; stroke-width: 2; stroke-dasharray: none; }
.empty-note { position: absolute; left: 30px; top: 30px; color: var(--muted); }

.node { position: absolute; background: var(--panel); border: 1px solid var(--line);
  border-radius: 8px; padding: 5px 9px 5px 11px; cursor: pointer; overflow: hidden;
  box-shadow: 0 1px 2px rgba(0,0,0,.05); }
.node:hover { border-color: var(--accent); }
.node.sel { outline: 2px solid var(--sel); outline-offset: 1px; }
.node.hit { background: var(--hit); }
.node.dim { opacity: .28; }
.node .r1 { display: flex; gap: 6px; align-items: center; font-size: 12px; white-space: nowrap; }
.node .lab { font-weight: 700; font-variant-numeric: tabular-nums; }
.node .txt { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.node .flag { font-size: 10px; font-weight: 700; border-radius: 3px; padding: 0 4px; line-height: 15px; }
.flag.later { background: var(--warn-bg); color: var(--warn-ink); }
.flag.cite { border: 1px solid var(--faint); color: var(--muted); }
.flag.now { background: var(--now); color: #fff; }
.node.root { background: var(--ink); color: var(--panel); border-color: var(--ink); }
.node.root .txt { white-space: normal; font-size: 12px; opacity: .8; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.node.q { border-left: 4px solid var(--muted); }
.node.q.st-open { border-left-color: var(--OPEN); }
.node.q.st-answered { border-left-color: var(--CONFIRMED); }
.node.q.st-superseded, .node.q.st-abandoned { border-left-color: var(--ABANDONED); border-style: dashed; border-left-style: solid; }
.node.q.st-superseded .txt, .node.q.st-abandoned .txt { color: var(--muted); }
.node.q.now { box-shadow: 0 0 0 3px var(--now); }
.st { font-size: 10px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
.node.a { border-left: 4px solid var(--v); }
.pill { font-size: 10px; font-weight: 700; color: #fff; background: var(--v); border-radius: 3px; padding: 0 5px; line-height: 15px; letter-spacing: .03em; }
.pill.OPEN { background: transparent; color: var(--v); box-shadow: inset 0 0 0 1px var(--v); }
.tg { margin-left: auto; font-size: 11px; color: var(--muted); border: 1px solid var(--line);
  border-radius: 4px; padding: 0 5px; line-height: 16px; background: var(--panel); }
.tg:hover { border-color: var(--accent); color: var(--accent); }

#detail { border-left: 1px solid var(--line); background: var(--panel); overflow: auto; padding-bottom: 40px; }
#detail .hd { padding: 14px 16px 10px; border-bottom: 1px solid var(--line); }
#detail .hd .t { font-size: 16px; font-weight: 700; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
#detail .hd .s { color: var(--muted); font-size: 12px; margin-top: 4px; }
.sec { padding: 8px 16px; }
.sec > .k { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--faint); margin-bottom: 3px; }
.sec pre, .card pre { margin: 0; white-space: pre-wrap; word-break: break-word; font: inherit; }
.sec.interp pre { background: var(--interp-bg); color: var(--interp-ink); padding: 6px 8px; border-radius: 6px; font-style: italic; }
.sec.interp > .k::after { content: "  - interpretation of n=1, not a measurement"; text-transform: none; letter-spacing: 0; }
.sec.measured pre { background: var(--code); padding: 6px 8px; border-radius: 6px; }
.sec.warn pre, .sec.warn .card { background: var(--warn-bg); color: var(--warn-ink); }
.sec ul { margin: 0; padding-left: 18px; }
.sec li { margin: 2px 0; }
.card { border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; margin: 4px 0; font-size: 13px; }
.card .ck { color: var(--faint); font-size: 11px; }
a.jump { color: var(--accent); cursor: pointer; text-decoration: none; font-weight: 600; }
a.jump:hover { text-decoration: underline; }
.list-row { display: flex; gap: 6px; align-items: baseline; padding: 3px 0; border-bottom: 1px dashed var(--line); font-size: 13px; }
.list-row .sub { color: var(--muted); font-size: 12px; }
.clamp { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.muted { color: var(--muted); }

@media (max-width: 1000px) {
  body { overflow: auto; }
  main { grid-template-columns: 1fr; grid-template-rows: auto 70vh auto; }
  #side { max-height: 30vh; border-right: 0; border-bottom: 1px solid var(--line); }
  #detail { border-left: 0; border-top: 1px solid var(--line); }
}
</style>
</head>
<body>
<header>
  <h1>Sainpost</h1>
  <span class="src" id="src"></span>
  <span class="grow"></span>
  <div class="legend" id="legend"></div>
  <div class="tools">
    <input id="q" type="search" placeholder="Search this project (Enter: next)">
    <span id="hits"></span>
    <button class="btn" id="now" title="Scroll to where the work is">Now</button>
    <button class="btn" id="expand" title="Show every attempt">Expand</button>
    <button class="btn" id="fold" title="Hide attempts, keep the questions">Questions only</button>
    <label><input type="checkbox" id="pb" checked> prompted_by</label>
    <button class="btn" id="zout" title="Zoom out (Ctrl+wheel)">-</button>
    <button class="btn" id="z100" title="Actual size">100%</button>
    <button class="btn" id="zin" title="Zoom in (Ctrl+wheel)">+</button>
    <button class="btn" id="reload" title="Read the notebook again" hidden>Reload</button>
  </div>
</header>
<main>
  <nav id="side"><h2>Projects</h2><div id="plist"></div></nav>
  <section id="canvas"><div id="sizer"><div id="stage"><svg id="edges"></svg></div></div></section>
  <aside id="detail"></aside>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("data").textContent);
const VERDICTS = ["CONFIRMED", "FALSIFIED", "INCONCLUSIVE", "ABANDONED", "BLOCKED", "OPEN"];
const NODE_W = 300, ROOT_W = 230, COL = 350, ROW = 58, PAD = 28;
const H = { root: 58, q: 50, a: 42 };
const LINKED = new Set(["prompted_by", "prompted_these", "in service of", "opened under it",
  "attempts", "supersedes", "superseded_by", "under", "shown_by"]);
const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

// ---- state, and the URL that carries it --------------------------------
const S = { p: null, sel: null, folded: new Set(), zoom: 1, query: "", hits: [], hit: -1, tree: null };

function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  return { p: h.get("p"), n: h.get("n") };
}
function writeHash() {
  const h = new URLSearchParams();
  if (S.p) h.set("p", S.p.project);
  if (S.sel && S.sel.kind !== "root") h.set("n", S.sel.id);
  history.replaceState(null, "", "#" + h.toString());
}

// ---- header ------------------------------------------------------------
$("src").textContent = DATA.notebook + "  -  read " + DATA.read_at.replace("T", " ");
for (const v of VERDICTS) {
  const s = el("span"); const i = el("i"); i.style.background = `var(--${v})`;
  s.append(i, v); $("legend").append(s);
}
if (DATA.live) { $("reload").hidden = false; $("reload").onclick = () => location.reload(); }

// ---- projects ----------------------------------------------------------
function verdictCounts(p) {
  const c = {};
  for (const q of p.trail.trail) for (const a of q.attempts) c[a.verdict] = (c[a.verdict] || 0) + 1;
  return c;
}
function vbar(counts) {
  const bar = el("div", "vbar");
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (!total) return bar;
  for (const v of VERDICTS) if (counts[v]) {
    const s = el("span"); s.style.width = (100 * counts[v] / total) + "%";
    s.style.background = `var(--${v})`; s.title = `${counts[v]} ${v}`; bar.append(s);
  }
  return bar;
}
function drawProjects() {
  const list = $("plist"); list.textContent = "";
  const ps = [...DATA.projects].sort((a, b) => (b.questions - a.questions) || a.project.localeCompare(b.project));
  for (const p of ps) {
    const d = el("div", "proj" + (p.questions ? "" : " empty") + (S.p === p ? " on" : ""));
    const nm = el("div", "nm", p.project);
    if (p.open_attempts.length) nm.append(el("span", "tag open", `${p.open_attempts.length} OPEN`));
    if (p.blocked_on.length) nm.append(el("span", "tag blocked", "BLOCKED"));
    if (p.waiting_on_you.length) nm.append(el("span", "tag waiting", `${p.waiting_on_you.length} waiting`));
    d.append(nm, el("div", "ct", `${p.questions} questions - ${p.attempts} attempts`), vbar(verdictCounts(p)));
    d.title = p.description || "";
    d.onclick = () => openProject(p);
    list.append(d);
  }
}

// ---- the tree ----------------------------------------------------------
function buildTree(p) {
  const root = { kind: "root", id: "@", data: p, children: [], parent: null };
  const byQ = new Map();
  for (const q of p.trail.trail) byQ.set(q.question, { kind: "q", id: q.question, data: q, children: [] });
  for (const q of p.trail.trail) {
    const n = byQ.get(q.question);
    for (const a of q.attempts) n.children.push({ kind: "a", id: a.attempt, data: a, children: [], parent: n });
  }
  for (const q of p.trail.trail) {
    const n = byQ.get(q.question);
    n.parent = (q.under && byQ.get(q.under)) || root;
    n.parent.children.push(n);
  }
  const index = new Map([["@", root]]);
  (function walk(n) { index.set(n.id, n); n.children.forEach(walk); })(root);
  return { root, index };
}
function kids(n) { return S.folded.has(n.id) ? [] : n.children; }
function hidden(n) {
  let c = 0;
  (function count(m) { for (const k of m.children) { c++; count(k); } })(n);
  return c;
}
function layout(root) {
  let row = 0, maxX = 0;
  const nodes = [];
  (function place(n, depth) {
    nodes.push(n);
    n.w = depth === 0 ? ROOT_W : NODE_W;
    n.h = H[n.kind];
    n.x = depth === 0 ? PAD : PAD + ROOT_W + 50 + (depth - 1) * COL;
    maxX = Math.max(maxX, n.x + n.w);
    const ks = kids(n);
    if (ks.length) {
      ks.forEach((k) => place(k, depth + 1));
      n.y = (ks[0].y + ks[ks.length - 1].y) / 2;
    } else {
      n.y = PAD + row * ROW + ROW / 2; row++;
    }
  })(root, 0);
  return { nodes, width: maxX + PAD + 90, height: PAD * 2 + row * ROW };
}

function nodeEl(n, p) {
  const d = el("div", "node " + n.kind);
  d.style.cssText = `left:${n.x}px;top:${n.y - n.h / 2}px;width:${n.w}px;height:${n.h}px`;
  const r1 = el("div", "r1");
  let text, full;
  if (n.kind === "root") {
    r1.append(el("span", "lab", p.project));
    text = p.description || p.repo || "";
  } else if (n.kind === "q") {
    const q = n.data;
    d.classList.add("st-" + q.status);
    r1.append(el("span", "lab", q.question), el("span", "st", q.status));
    if (p.now === q.question) { d.classList.add("now"); r1.append(el("span", "flag now", "NOW")); }
    if ((q.learned_later || []).length) r1.append(el("span", "flag later", "LATER"));
    full = (S.p.bodies[q.question] || {}).text || q.text;
    text = q.headline || full;
  } else {
    const a = n.data;
    d.style.setProperty("--v", `var(--${a.verdict})`);
    r1.append(el("span", "lab", a.attempt), el("span", "pill " + a.verdict, a.verdict));
    if ((a.learned_later || []).length) r1.append(el("span", "flag later", "LATER"));
    if ((a.false_readings || []).length) r1.append(el("span", "flag later", "FALSE READING"));
    const b = S.p.bodies[a.attempt] || {};
    if (b["the result rests on"]) r1.append(el("span", "flag cite", "CITES"));
    if (a.prompted_by) r1.append(el("span", "st", "<- " + a.prompted_by));
    full = b.hypothesis || a.hypothesis;
    text = a.headline || full;
  }
  if (n.children.length) {
    const folded = S.folded.has(n.id);
    const t = el("span", "tg", folded ? `+${hidden(n)}` : "-");
    t.title = folded ? "Show what is under this" : "Hide what is under this";
    t.onclick = (ev) => { ev.stopPropagation(); toggle(n); };
    r1.append(t);
  }
  d.append(r1);
  if (text) d.append(el("div", "txt", text));
  d.title = full && full !== text ? full : (text || "");
  d.onclick = (ev) => { ev.stopPropagation(); select(n); };
  n.el = d;
  return d;
}

function curve(x1, y1, x2, y2) {
  const m = (x1 + x2) / 2;
  return `M${x1},${y1} C${m},${y1} ${m},${y2} ${x2},${y2}`;
}
function svg(tag, attrs) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

function draw(keepScroll) {
  const p = S.p, c = $("canvas");
  const sx = c.scrollLeft, sy = c.scrollTop;
  const stage = $("stage");
  for (const e of [...stage.querySelectorAll(".node, .empty-note")]) e.remove();
  const edges = $("edges"); edges.textContent = "";
  const defs = svg("defs", {});
  for (const [id, color] of [["ar", "var(--muted)"], ["arp", "var(--accent)"]]) {
    const m = svg("marker", { id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
    const path = svg("path", { d: "M0,0 L10,5 L0,10 z" }); path.style.fill = color;
    m.append(path); defs.append(m);
  }
  edges.append(defs);

  const { nodes, width, height } = layout(S.tree.root);
  S.nodes = nodes;
  stage.style.width = width + "px"; stage.style.height = height + "px";
  edges.setAttribute("width", width); edges.setAttribute("height", height);
  $("sizer").style.width = width * S.zoom + "px";
  $("sizer").style.height = height * S.zoom + "px";
  stage.style.transform = `scale(${S.zoom})`;

  const shown = new Set(nodes.map((n) => n.id));
  for (const n of nodes) {
    stage.append(nodeEl(n, p));
    for (const k of kids(n)) edges.append(svg("path", { class: "e", d: curve(n.x + n.w, n.y, k.x, k.y) }));
  }
  // A replacement stands where the replaced question stood: the two are
  // siblings, and the dashed arrow on their left says one replaced the other.
  for (const n of nodes) {
    if (n.kind !== "q" || !n.data.superseded_by || !shown.has(n.data.superseded_by)) continue;
    const m = S.tree.index.get(n.data.superseded_by);
    const bend = 26 + Math.min(60, Math.abs(m.y - n.y) / 8);
    edges.append(svg("path", { class: "e sup", "marker-end": "url(#ar)",
      d: `M${n.x},${n.y} C${n.x - bend},${n.y} ${m.x - bend},${m.y} ${m.x - 1},${m.y}` }));
  }
  // prompted_by: which result sent somebody on. Drawn on the right, where
  // the attempts are, and bold for whatever is selected.
  if ($("pb").checked) {
    for (const n of nodes) {
      if (n.kind !== "a" || !n.data.prompted_by || !shown.has(n.data.prompted_by)) continue;
      const src = S.tree.index.get(n.data.prompted_by);
      const hot = S.sel && (S.sel === n || S.sel === src);
      const x1 = src.x + src.w, x2 = n.x + n.w;
      const bend = 30 + Math.min(80, Math.abs(n.y - src.y) / 6);
      const bx = Math.max(x1, x2) + bend;
      edges.append(svg("path", { class: "e pb" + (hot ? " hot" : ""), "marker-end": "url(#arp)",
        d: `M${x1},${src.y} C${bx},${src.y} ${bx},${n.y} ${x2 + 1},${n.y}` }));
    }
  }
  if (!p.trail.trail.length) {
    const e = el("div", "empty-note", "No question has been asked in this project yet.");
    e.style.left = (PAD + ROOT_W + 40) + "px";
    stage.append(e);
  }
  if (S.sel && S.sel.el) S.sel.el.classList.add("sel");
  paintHits();
  if (keepScroll) { c.scrollLeft = sx; c.scrollTop = sy; }
}

function toggle(n) {
  if (S.folded.has(n.id)) S.folded.delete(n.id); else S.folded.add(n.id);
  draw(true);
}
function reveal(n) {
  let changed = false;
  for (let m = n.parent; m; m = m.parent) if (S.folded.delete(m.id)) changed = true;
  return changed;
}
function scrollTo(n) {
  const c = $("canvas");
  // Keep the tree's left edge in view whenever the node fits beside it.
  const right = (n.x + n.w) * S.zoom + 40;
  c.scrollTo({ left: right <= c.clientWidth ? 0 : right - c.clientWidth,
               top: Math.max(0, n.y * S.zoom - c.clientHeight / 2), behavior: "smooth" });
}
function select(n, scroll) {
  if (reveal(n)) draw(true);
  S.sel = n;
  for (const e of document.querySelectorAll(".node.sel")) e.classList.remove("sel");
  if (n.el) n.el.classList.add("sel");
  if ($("pb").checked) draw(true);
  showDetail(n);
  writeHash();
  if (scroll) scrollTo(n);
}
function jump(label) {
  const n = S.tree.index.get(label);
  if (n) { select(n, true); return; }
  const body = S.p.bodies[label];
  if (body) showBody(label, body);
}

// ---- search ------------------------------------------------------------
function haystack(n) {
  if (n._hay != null) return n._hay;
  const b = S.p.bodies[n.id];
  const words = [n.id];
  (function collect(v) {
    if (v == null) return;
    if (typeof v === "object") { for (const x of Object.values(v)) collect(x); return; }
    words.push(String(v));
  })(n.kind === "root" ? null : (b || n.data));
  n._hay = words.join(" | ").toLowerCase();
  return n._hay;
}
function runSearch() {
  S.query = $("q").value.trim().toLowerCase();
  S.hits = []; S.hit = -1;
  if (S.query) {
    const all = [];
    (function walk(n) { all.push(n); n.children.forEach(walk); })(S.tree.root);
    S.hits = all.filter((n) => n.kind !== "root" && haystack(n).includes(S.query));
    let changed = false;
    for (const n of S.hits) if (reveal(n)) changed = true;
    if (changed) { draw(true); return; }
  }
  paintHits();
}
function paintHits() {
  const hit = new Set(S.hits);
  for (const n of S.nodes || []) {
    if (!n.el) continue;
    n.el.classList.toggle("hit", hit.has(n));
    n.el.classList.toggle("dim", !!S.query && !hit.has(n) && n.kind !== "root");
  }
  $("hits").textContent = S.query ? `${S.hits.length} found` : "";
}
$("q").addEventListener("input", runSearch);
$("q").addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter" || !S.hits.length) return;
  S.hit = (S.hit + (ev.shiftKey ? S.hits.length - 1 : 1)) % S.hits.length;
  select(S.hits[S.hit], true);
  $("hits").textContent = `${S.hit + 1} / ${S.hits.length}`;
});

// ---- the panel ---------------------------------------------------------
const HEADER_KEYS = new Set(["question", "attempt", "verdict", "status", "text", "hypothesis",
  "defect", "request", "labels in text from another notebook"]);

function linkify(parent, s) {
  const m = /^((?:[\w.-]+\/)?[QA]\d+(?:@[a-z0-9]+)?)\b/.exec(s);
  if (!m || m[1].includes("/")) { parent.append(s); return; }
  const a = el("a", "jump", m[1]); a.onclick = () => jump(m[1]);
  parent.append(a, s.slice(m[1].length));
}
function value(key, v) {
  if (v == null || v === "" || (Array.isArray(v) && !v.length)) return null;
  if (typeof v !== "object") {
    const s = String(v);
    if (LINKED.has(key)) { const d = el("div"); linkify(d, s); return d; }
    return el("pre", null, s);
  }
  if (Array.isArray(v)) {
    if (v.every((x) => typeof x !== "object")) {
      const ul = el("ul");
      for (const x of v) { const li = el("li"); if (LINKED.has(key)) linkify(li, String(x)); else li.append(String(x)); ul.append(li); }
      return ul;
    }
    const box = el("div");
    for (const x of v) box.append(card(x));
    return box;
  }
  return card(v);
}
function card(obj) {
  const c = el("div", "card");
  if (typeof obj !== "object" || obj === null) { c.append(el("pre", null, String(obj))); return c; }
  for (const [k, v] of Object.entries(obj)) {
    const x = value(k, v);
    if (!x) continue;
    c.append(el("div", "ck", k), x);
  }
  return c;
}
function section(key, v, cls) {
  const x = value(key, v);
  if (!x) return null;
  const s = el("div", "sec" + (cls ? " " + cls : ""));
  s.append(el("div", "k", key), x);
  return s;
}
function classFor(key, kind) {
  if (/INTERPRETATION/.test(key)) return "interp";
  if (/MEASURED/.test(key)) return "measured";
  // On an attempt, what was learned later is that the number should not be
  // believed. On a question it is what turned out to be true since.
  if (/MOVED|false/.test(key) || (kind === "a" && key === "learned later")) return "warn";
  return "";
}
function head(title, sub, pill) {
  const d = $("detail"); d.textContent = "";
  const hd = el("div", "hd"), t = el("div", "t");
  t.append(title);
  if (pill) t.append(pill);
  hd.append(t);
  if (sub) hd.append(el("div", "s", sub));
  d.append(hd);
  return d;
}
function body(d, obj, kind) {
  for (const [k, v] of Object.entries(obj)) {
    if (HEADER_KEYS.has(k)) continue;
    const s = section(k, v, classFor(k, kind));
    if (s) d.append(s);
  }
  const legend = obj["labels in text from another notebook"];
  if (legend) {
    const s = section("labels in text from another notebook", legend, "warn");
    if (s) d.append(s);
  }
}
function showBody(label, b) {
  const d = head(label, b.owner ? `${b.reported_by || b.asked_by || ""} -> ${b.owner}` : "");
  if (b.hypothesis) d.append(section("hypothesis", b.hypothesis));
  body(d, b);
}
function showDetail(n) {
  if (n.kind === "root") return showProject(S.p);
  const b = S.p.bodies[n.id] || n.data;
  if (n.kind === "q") {
    const d = head(n.id, n.data.status + (S.p.now === n.id ? "  -  where the work is now" : ""));
    d.append(section("question", b.text || n.data.text));
    body(d, b, "q");
    return;
  }
  const pill = el("span", "pill " + n.data.verdict, n.data.verdict);
  pill.style.setProperty("--v", `var(--${n.data.verdict})`);
  const d = head(n.id, null, pill);
  d.append(section("hypothesis", b.hypothesis || n.data.hypothesis));
  if (n.data.defect) {
    const s = el("div", "sec warn"); s.append(el("div", "k", "not measured -- the apparatus failed"));
    const x = el("div"); const lab = n.data.defect.split(" ")[0];
    const a = el("a", "jump", lab); a.onclick = () => jump(lab);
    x.append(a, n.data.defect.slice(lab.length)); s.append(x); d.append(s);
  }
  body(d, b, "a");
}
function rows(d, title, items, render) {
  if (!items || !items.length) return;
  const s = el("div", "sec"); s.append(el("div", "k", `${title} (${items.length})`));
  for (const it of items) s.append(render(it));
  d.append(s);
}
function attemptRow(a) {
  const r = el("div", "list-row");
  const l = el("a", "jump", a.attempt); l.onclick = () => jump(a.attempt);
  const pill = el("span", "pill " + a.verdict, a.verdict); pill.style.setProperty("--v", `var(--${a.verdict})`);
  const t = el("div"); t.append(el("div", "clamp", a.headline || a.hypothesis));
  if (a.result) t.append(el("div", "sub clamp", "-> " + a.result));
  r.append(l, pill, t);
  return r;
}
function questionRow(q) {
  const r = el("div", "list-row");
  const l = el("a", "jump", q.question); l.onclick = () => jump(q.question);
  const t = el("div"); t.append(el("div", "clamp", q.headline || q.text));
  const n = Object.entries(q.verdicts || {}).map(([v, c]) => `${c} ${v}`).join(", ");
  t.append(el("div", "sub", q.status + (n ? "  -  " + n : "")));
  r.append(l, t);
  return r;
}
function labelRow(line) {
  const r = el("div", "list-row"); linkRD(r, line); return r;
}
function linkRD(parent, line) {
  const m = /^([RDQA]\d+(?:@[0-9a-z]+)?)/.exec(line);
  if (!m) { parent.append(line); return; }
  const a = el("a", "jump", m[1]); a.onclick = () => jump(m[1]);
  parent.append(a, line.slice(m[1].length));
}
function showProject(p) {
  const t = p.trail;
  const d = head(p.project, p.repo || "");
  if (p.description) d.append(section("description", p.description));
  d.append(section("tally", t.tally));
  const now = t.trail.find((q) => q.question === p.now);
  if (now) rows(d, "where the work is now", [now], questionRow);
  rows(d, "open attempts", t.open_now.filter((a) => a.verdict === "OPEN"), attemptRow);
  rows(d, "blocked on", p.blocked_on, labelRow);
  rows(d, "waiting on you", p.waiting_on_you, labelRow);
  if (t.reformulated && t.reformulated.length) {
    const s = el("div", "sec"); s.append(el("div", "k", "the question moved"));
    for (const chain of t.reformulated) {
      const r = el("div", "list-row");
      chain.forEach((q, i) => { if (i) r.append(" -> "); const a = el("a", "jump", q); a.onclick = () => jump(q); r.append(a); });
      s.append(r);
    }
    d.append(s);
  }
  rows(d, "closed off -- do not re-derive these", t.closed_off, attemptRow);
  rows(d, "standing -- what the next step rests on", t.standing, attemptRow);
  rows(d, "not settled", t.open_now.filter((a) => a.verdict !== "OPEN"), attemptRow);
}

// ---- opening a project -------------------------------------------------
function openProject(p, label) {
  S.p = p; S.sel = null; S.folded = new Set(); S.hits = []; S.query = ""; $("q").value = "";
  S.tree = buildTree(p);
  // A big tree opens with its questions showing and the attempts folded
  // under them, except on the branch being worked.
  const attempts = p.trail.trail.reduce((n, q) => n + q.attempts.length, 0);
  if (attempts > 60) for (const q of p.trail.trail) if (q.attempts.length && !q.live) S.folded.add(q.question);
  drawProjects();
  draw(false);
  const n = label && S.tree.index.get(label);
  if (n) select(n, true);
  else {
    S.sel = S.tree.root; S.tree.root.el && S.tree.root.el.classList.add("sel");
    showProject(p); writeHash();
    const now = p.now && S.tree.index.get(p.now);
    if (now) scrollTo(now); else $("canvas").scrollTo(0, 0);
  }
}

$("now").onclick = () => { const n = S.p && S.p.now && S.tree.index.get(S.p.now); if (n) select(n, true); };
$("expand").onclick = () => { S.folded.clear(); draw(true); };
$("fold").onclick = () => {
  for (const q of S.p.trail.trail) if (q.attempts.length) S.folded.add(q.question);
  draw(true);
};
$("pb").onchange = () => draw(true);

// ---- zoom and pan ------------------------------------------------------
function zoomTo(z, cx, cy) {
  const c = $("canvas");
  z = Math.min(2, Math.max(0.25, z));
  const r = c.getBoundingClientRect();
  const px = cx == null ? c.clientWidth / 2 : cx - r.left, py = cy == null ? c.clientHeight / 2 : cy - r.top;
  const wx = (c.scrollLeft + px) / S.zoom, wy = (c.scrollTop + py) / S.zoom;
  S.zoom = z;
  draw(false);
  c.scrollLeft = wx * z - px; c.scrollTop = wy * z - py;
}
$("zin").onclick = () => zoomTo(S.zoom * 1.2);
$("zout").onclick = () => zoomTo(S.zoom / 1.2);
$("z100").onclick = () => zoomTo(1);
$("canvas").addEventListener("wheel", (ev) => {
  if (!ev.ctrlKey) return;
  ev.preventDefault();
  zoomTo(S.zoom * (ev.deltaY < 0 ? 1.1 : 1 / 1.1), ev.clientX, ev.clientY);
}, { passive: false });
(function pan() {
  const c = $("canvas"); let start = null;
  c.addEventListener("mousedown", (ev) => {
    if (ev.button !== 0 || ev.target.closest(".node")) return;
    start = { x: ev.clientX, y: ev.clientY, l: c.scrollLeft, t: c.scrollTop, moved: false };
    c.classList.add("drag");
  });
  window.addEventListener("mousemove", (ev) => {
    if (!start) return;
    const dx = ev.clientX - start.x, dy = ev.clientY - start.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) start.moved = true;
    c.scrollLeft = start.l - dx; c.scrollTop = start.t - dy;
  });
  window.addEventListener("mouseup", () => {
    if (start && !start.moved && S.tree) select(S.tree.root);
    start = null; c.classList.remove("drag");
  });
})();

// ---- start -------------------------------------------------------------
drawProjects();
const want = readHash();
const first = DATA.projects.find((p) => p.project === want.p)
  || [...DATA.projects].sort((a, b) => b.questions - a.questions)[0];
if (first) openProject(first, want.n);
else head("The notebook is empty", "note_start begins a project.");
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())

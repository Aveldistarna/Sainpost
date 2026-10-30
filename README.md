# Sainpost

*サインポスト* — Japanese for a signpost. Read it as *Saint Post* if you
like. Look closer and there is an AI in it.

A shared lab notebook for long investigations, exposed as an MCP server.
One database, every project on the machine.

## What it is for

A long investigation rarely fails by diverging. It fails when an unverified
intermediate gets promoted to a fact, and every later step is reasoned
correctly on top of it. The footing drops out and nothing reports an error.
You then re-derive hypotheses you already killed, because you do not know
that you are re-deriving them.

Filing does not fix that. A searchable reference answers *"is this known?"*,
which you only ask when you already suspect. Humans fixed it with two things
a reference cannot do, and both are built in here:

**A commitment made before the data.** `note_hypothesis` will not record an
attempt without its falsifier and an apparatus check. `note_result` has
nothing to attach a number to unless that pre-registration happened. There
is no update path anywhere — the record is append-only.

**A position you can see.** `note_trunk` prints where you are: the current
question, the chain of reformulations that led to it, one line per attempt
underneath. Being lost *is* the loss of position, so the trunk is small on
purpose and meant to be re-read at every checkpoint. Bodies come from
`note_open`.

## The shape of the record

```
project ─ question ─ attempt
```

- **The position does not move while an attempt is open.** Open attempts
  *are* the position — one question, with every arm open under it — and the
  trunk lists only the current question's attempts, so moving it made the falsifier
  somebody had committed to vanish from the view they re-read at every
  checkpoint. It fired when another project filed a question, and equally
  when you superseded your own question mid-measurement. The second case came
  back unnoticed: this paragraph said it was fixed, no test held it, and the
  later change that moves the pointer off a closed question moved it off a
  superseded one with work still open under it. The position is now read
  from the open work itself, and a test holds it. A question asked in
  the meantime waits, and becomes current when the last open attempt closes
  — which `note_ask` promised for a long time before anything did it. Which
  question that is, is recorded when it is *asked*: reconstructing it later
  needs "asked in the meantime" from the row, and both candidates are wrong.
  The numbering says only which was written first, so a tree laid out in
  advance sends the position to the highest number instead of where anyone
  was working; and these timestamps are whole seconds, so by the clock a
  question asked in the same second as the attempt it interrupted was never
  in the meantime at all.
- **Work can be opened under a question that is not the current one**
  (`note_hypothesis(question="Q3")`), and the position follows it there. The
  pointer used to move only to the question most recently *asked*, so a tree
  laid out before any work began left every requirement but the last
  unreachable: the only order that worked was to open one question and
  measure it before writing the next, which is the opposite of laying the
  argument out first. Refused while work is open under another question —
  that is what one front means — and nothing moves the position without
  opening work there, so it never points at a question nobody is on.
- **The position never rests on a closed question while another is open.**
  It is read past one, onto the most recently opened. It used to move only
  at the instant a question closed, so a pointer already resting on a closed
  one stayed there for good: this repository's own project sat on answered
  Q7 with Q5 open, and `note_hypothesis` refused it everything, telling it to
  ask a new question in order to reach an open one.
- A question can be **superseded** by another question. Reformulating the
  question is usually the actual finding, so it is a node, not a rename —
  its attempts stay readable instead of dangling under a dead question.
- A question can also stand **under** another: what its answer will rest on.
  That is the opposite relation, and until it existed the only one available
  said the earlier question had been *wrong*.
- Attempts link by **`prompted_by`**: which prior *result* made you try
  this. Not a taxonomic parent; you never know the parent while you are
  lost. You always know which number you had just read.
- `result` is measurement, `verdict` is the call, `why_now` is
  interpretation of n=1 and is labelled as such wherever it is rendered.
  The narrative of a path is exactly where interpretation gets promoted to
  measurement, so the three never share a field.

## Install

```bash
claude mcp add --scope user sainpost -- python /home/you/work/Sainpost/launch.py
```

```powershell
claude mcp add --scope user sainpost -- python C:\Users\me\work\Sainpost\launch.py
```

`launch.py` builds `.venv/` from `requirements.txt` on first use (one
dependency, `mcp`) and then serves stdio from inside it. Nothing else to
start.

It takes the platform from `os.name`, so the same command is the whole
install on either. Two things differ underneath it: the venv keeps its
interpreter in `Scripts/` rather than `bin/`, and Windows has no `exec`.
`os.execv()` there *spawns* a replacement and exits the process the MCP
client launched, so the client sees the server it is holding disappear
mid-handshake and reads it as a crash — on Windows the launcher stays alive
as a thin parent instead, handing the child its own stdio handles.

The database lives at `~/.local/share/sainpost/research.db`, and at
`%LOCALAPPDATA%\sainpost\research.db` on Windows;
`SAINPOST_DB` moves it. It is plain SQLite — if this server is ever
abandoned, the notebook still opens.

Windows deliberately ignores `XDG_DATA_HOME`, which git-bash, msys and
WSL-interop shells all export. The notebook is machine-wide — that is the
whole reason it lives outside any repository — so a path that depended on
which shell happened to start the server would quietly give the machine a
*second* notebook, and the two are not distinguishable from inside: each
looks like a complete record that is simply missing the other's work.

It runs in WAL mode, which is what lets two agents share it, and that has a
trap worth knowing: recent writes live in `research.db-wal`, so `cp
research.db elsewhere` on a *live* notebook yields a file that opens cleanly
and contains nothing. Three sessions of records were lost here to exactly
that. `Store.close()` checkpoints, so a notebook nobody is attached to is
whole in the one file — and `backup.py` is always safe, because it goes
through sqlite's own backup API rather than the filesystem.

An older notebook is brought to the current shape by the first session that
opens it, and every other session opening it in the same instant waits and
finds it done. Almost all of that is adding columns. The exceptions are
constraints SQLite cannot relax in place, and those tables are rebuilt in
SQLite's own order — the new table built beside the old, then renamed into
place. The first rebuild here renamed the old table out of the way first,
and SQLite rewrites every reference to a renamed table: `defect_notes` came
out pointing at `defects_was`, dropped a moment later, and any note on a
defect after that would have failed with *no such table*. A notebook in that
state is repaired on open.

A pointer for every agent on the machine belongs in `~/.claude/CLAUDE.md`:
name `note_projects()` as the entry point (it is the only tool that needs no
arguments, and every other one wants a project name you do not have yet) and
point at this file. Nothing else — it is loaded into every session on the
machine, including all the ones that will never open a notebook.

## Seeing the whole path

`note_trunk` answers *where am I* and stays small by showing one question.
That is the wrong shape for the other thing an agent arrives wanting: what
has already been ruled out here. `note_path(project)` is that view — the
digest first, because a `FALSIFIED` row is the most valuable kind in this
record and is worth nothing unread:

```
PROJECT  t3-sweep
         1 BLOCKED, 1 CONFIRMED, 3 FALSIFIED; 1 question(s) answered (1 not endorsed by the user)
         the question moved:  Q1* -> Q2 -> Q3     (* answered)

  CLOSED OFF -- carried to a verdict already. Do not re-derive these.
      A2   FALSIFIED   frontage() takes a cost argument we are not passing
           -> signature is (pad, repair=False); dir(escape) == ['frontage']
      A4   FALSIFIED   MAX_DETOUR_MM is defined somewhere we can read
           -> named once in a docstring, defined in no scope

  STANDING -- what anything you do next will be resting on
      A1   the via cost never reaches the joined-span computation
           -> spent entirely on `c > 0`; N=6 at every cost

  NOT SETTLED
      A3   BLOCKED     --repair raises the joined count above 6/8
           D1 -> corridor-team

  THE PATH
    Q1  why is the count identical at every via cost  [answered, not endorsed by the user]
        A1   CONFIRMED   the via cost never reaches the computation
        ANSWER  (not endorsed by the user) the sweep is not measuring anything
    Q2  can the board team wire the cost through themselves  [became Q3]
        A2   FALSIFIED   frontage() takes a cost argument  <-A1
        A3   BLOCKED     --repair raises the count  <-A2
```

The verdict that closed each line comes with the number that closed it —
*"MAX_DETOUR_MM is defined somewhere"* on its own does not tell anyone it is
not. `BLOCKED`, `INCONCLUSIVE` and `OPEN` are kept out of **closed off**:
none of them means ruled out, and filing them there would retire live work.
Still one line per node; bodies come from `note_open`.

Three cold agents in a row rebuilt this by hand, calling `note_trunk` once
per question after guessing the labels.

**Every node carries its own line, written by whoever wrote the body.** A
question, a hypothesis, a result, an answer, a note: if the body is longer
than 96 characters, `headline=` is required, and that is the line every view
but `note_open` shows. Shorter bodies need none — they are already their own
line, and a field that asks for a second copy of a one-sentence question is
how `why_now` came to hold paragraphs explaining that it did not apply.

```
note_result(project, <2,000 characters of measurement>, "CONFIRMED",
            headline="23件中20件を説明、残り3件は記録の欠落")
```

The line used to be the body with a machine's cut in it — a summary nobody
wrote and nobody checked, which is the one kind of claim this record refuses
everywhere else. It also cut badly. Backing up to the last space assumes
there is one near the cut; a Japanese line has none, so a 97-character
question came back as its four-character tag, and a tree of them said
nothing at all. Rows written before headlines existed are still cut to fit,
and no headline is invented for them: there is no edit path here, and a
summary written now by somebody who was not there is exactly what the field
exists to prevent.

**A trail too big for one reply becomes the map of itself.** `note_path`
renders the whole thing while the whole thing is under 6,000 bytes, and
otherwise renders a page: where the work is, the open questions, what was
worked most recently — one line each, with what came of the attempts under
them as a count — the rest counted, and the calls that open any of it.

```
PROJECT  pcbrouter   /home/you/work/PcbRouter
         6 ABANDONED, 6 BLOCKED, 116 CONFIRMED, 126 FALSIFIED, 21 INCONCLUSIVE
         the whole trail is 27,813 bytes; this is the map of it
  NOW    Q38  4層に残った配線のうち何本が…   55 CONFIRMED, 58 FALSIFIED, 5 BLOCKED
  OPEN   Q11  配置そのものを機械が決められるか…   (nothing tried)
  RECENT Q40  難しさの違う盤を並べて…  [answered, not endorsed by the user]   1 CONFIRMED
         ... and 29 more question(s), by label
  READ   note_path('pcbrouter', question='Q<n>')   one branch, closer in
         note_trunk('pcbrouter')   where the work is now, with the falsifiers
         note_open('pcbrouter', 'A12,Q7')   any node whole
         note_search('<what you are about to try>')   across every project
```

That is 3,150 bytes for a project whose trail is 172,697 — the same move the
record itself makes, a line that says what is there with the body one call
below it, applied to the project as well as the node. A branch too big for
one reply does it again, and names its attempts by label and verdict so
there is something left to open.

**The ceiling underneath it.** Claude Code hands the model at most 25,000
tokens of an MCP result and warns past 10,000; over the limit the text goes
to a file and the model gets a path — the whole trail, present as a
filename. A branch is budgeted at 28,000 **bytes**, counted rather than
estimated. Bytes, because a Japanese line is three bytes and roughly one
token per character, so a budget in characters passes three times too much
of it through.

Three things keep a rendered trail inside it, and none of them is silence:

- **Each fact once.** The digest says what every attempt found and names the
  question it sits under; the tree is the shape — one line per question with
  the verdicts under it as a count. The hypothesis used to print in both, so
  275 attempts went through twice and came to 170 KB.
- **The map is never cut, the list is.** A project has far fewer questions
  than attempts, and a reader who cannot see a branch cannot ask for it
  either. What the budget cannot fit is the digest's older rows — the branch
  being worked first, then newest — and `note_path(question="Q7")` reads any
  branch whole.
- **What is left out is said**, in rows and in the call that opens them.

```
  NOT SHOWN: 115 standing; 132 closed off.
  note_path(question='Q<n>') opens one branch whole; note_open gives any label its body.
```

Measured across this machine's twelve projects: every one now renders
between 118 bytes and 4.8 KB, where the largest was 172,697 bytes — and the
trail that used to be 2.3× the client's hard limit is a page of about a
thousand tokens.

**One line per node is a size rule, not only a style one**, and it reaches
the question's own body: that was the last kind `note_path` printed whole,
unnoticed while questions were a sentence long and fatal the day one carried
its materials and its checklist into a tree view. Cutting a line to fit is
its own trap: backing up to the last space assumes there is one near the cut,
and a Japanese line has none, so a 97-character question came back as its
four-character tag, and a tree of them said nothing at all. It was written
here two lines below the example while the code printed whole answers, and on
the first project to accumulate real history that reached 65,177 bytes
against a 64 KiB tool-result ceiling — 359 bytes of headroom, one answer from
going over, with the client truncating rather than refusing, so a reader
would have got a path stopping mid-answer and nothing saying so. Answers and
postscripts were 94% of it. They are first lines now, the footer says how
many characters were left out, and `note_open` gives any of them whole.

The agent that reported it had checked whether an earlier fix had landed by
reading the SQLite file directly rather than calling `note_path` — pulling
every answer back to read one header line cost more than the check was worth.
A tool documented as the first thing to read when picking up work you did not
start, routed around by the one agent using it.

The same rule reaches what a **read of prior art** hands back: `already_tried`
and `in_flight` give one line of each result, which is where *"somebody
carried this to FALSIFIED, and here is what fell over"* lives. Four of them
arrived whole on a single pre-registration — 7,000 characters of numbers
nobody had asked for, with six more questions still to register.

And it reaches what a **write** hands back. A question carries its
materials and what it has to settle, and a paper's ran to 900 characters;
`note_hypothesis` and `note_request` each echoed it whole, so six calls in
one afternoon returned that body six times to the agent that had just
written it. Where a view names the question a node hangs off, it is one
line, and `note_open` on the question gives the rest.

## Looking at it yourself

Every view above is sized for a model's context. The person the agents are
working for arrives with the same two questions — where is the work, and what
has already been ruled out — and reads the answer faster as a picture:

```bash
python -m sainpost.view                   # serve it at http://127.0.0.1:8765/
python -m sainpost.view --out tree.html   # one self-contained file instead
```

Each project is drawn as its tree: questions under what they serve, attempts
under their question, coloured by verdict. A replacement stands beside the
question it replaced with a dashed arrow from the old one; `prompted_by` is
drawn on the right, bold for whatever is selected. Clicking a node gives its
whole body, with `why_now` marked as interpretation and the result as
measurement, the way `note_open` labels them. Clicking the project gives the
digest: where the work is, what is closed off, what is standing, who is
blocked on whom. A project with more than 60 attempts opens with them folded
under their questions, except on the branch being worked.

**It reads only, and the same code the tools run.** The notebook is opened
through `Store.read_only`, so SQLite itself refuses every write, and what is
drawn is `trail()` and `open()` — a second reading of the record written for
the page would be a second record that could disagree with the first. A
notebook no server has opened since the schema last grew is missing columns
those reads name, and a reader cannot add them; it says so and names them,
rather than failing inside `trail()`. Restarting the MCP server grows it.

Served, each reload reads the notebook again, so a page left open beside a
working agent shows what it wrote. The server answers only on 127.0.0.1 and
only to a request addressed to it by its own name: the page is every project on
the machine, including other people's work in flight. The written file
carries the same, so it is not a thing to publish.

## What was learned after the answer

An answered question used to be a dead end: it could not be superseded and
could not be answered again. That is right for the answer and wrong for the
question — six months on, an answer can turn out to have been partial, and
the only move was to open an unrelated new question that pointed at nothing.

`note_postscript` adds what was learned later. **The answer is never
touched:**

```
Q6  Does keeping the notebook's dump in git cost more than it is worth?  [answered, ...]
    ANSWER  (not endorsed by the user) Keep it in git; back the record up to Drive as well. ...
    LATER   (2026-09-07) The per-backup figure above is a floor, not an
            estimate. Every measurement behind it used synthetic attempts
            whose fields were the same string repeated hundreds of times ...
```

Both are kept, each with its own date, and both print wherever the answer
prints. Rewriting the original to look like what you know now would destroy
the one thing that made it worth recording — what was believed at the time,
and on what evidence — which is the same failure this record exists to stop,
wearing its own clothes.

An answer can accrue more than one over years; each is written once and never
edited, like everything else here. It is refused on an *open* question: there
is no answer to add to yet.

**On an attempt** (`A3`) it says what the *result* turned out to be worth.
Not for a finding that merely went out of date — that is a new attempt with
`prompted_by` pointing back, and the old measurement was never wrong, it
measured a world identified by its commit. This is for the measurement that
was **invalid and nobody noticed**: a sweep run against a broken rig produces
a plausible number, and written down it is indistinguishable from a sound
one. Nothing could mark it.

The verdict is not revisable and a note does not revise it. It is bound to a
falsifier written before the data — *"the count did not move"* either
happened or it did not. What the note adds is that the number should not be
believed, and why. `shown_by` names the attempt that demonstrated it; without
one the note renders as `INTERPRETATION`, the same way `why_now` does, because
a claim that a measurement was invalid is itself a claim and it is not free.

```
A1   INCONCLUSIVE  ...
     -> Sweep over 46 parameters ... 0 type mismatches ...
     LATER (2026-09-07, shown by A2) The sweep behind this result was
           measuring nothing ... the 0-of-46 figure should not be quoted
           as a measurement of anything.
```

**On a request or a defect** (`R3`, `D2`) it says what the *decision* or the
*fix* turned out to rest on. A decision's reason and a fix's cause carry
claims, and the first one to need this was a count: a request accepted
because *"16 of 89 near constraints are affected"*, whose check was fixed the
same afternoon and found 5 — two of the eleven that vanished refuted
outright by copper the router had already laid on that board. The
correction existed, in a commit message and a CLAUDE.md. The request still
said 16, as decided, to everyone arriving through the notebook, because
`note_postscript` refused the label.

The decision stands, the way a verdict does. Only on something closed — an
undecided request or an unresolved defect has nothing to add to, and a live
defect already has `note_query`. These labels are notebook-wide and the two
sides are different projects, so the note records **which side wrote it**,
and only those two sides may: a third project leaving notes on somebody
else's decision would be writing their record for them. `shown_by` is an
attempt of the writer's own project and prints with the project name, since
`A9` on a notebook-wide label names nothing. `note_open` takes `R` labels
too; a decided request otherwise left every view but
`note_defects(closed=True)`.

## A question that was answered can still be replaced

Answered is not the same state as superseded, and one refusal message used to
block both by naming the wrong one. A settled question is exactly the kind
whose *frame* later turns out to be wrong: the measurements under it stay
valid and stop meaning what they were taken to mean.

`note_ask(..., supersedes="Q1")` now works on an answered question. Q1 stays
answered, its answer and its attempts are untouched, and the two are linked
both ways; new measurement goes under the successor. There are three
different things here and each has its own path — the world changing (a new
attempt, with a commit that says which world), the frame changing
(supersession), and the measurement having been invalid (an attempt note).
Only the last two were missing.

## Whose answer it is

An answer is written by an agent. Mostly that is all it needs to be: the
answer to *why is the count identical at every via cost* is what the
measurements under it say, and the agent that took them writes it down. Some
questions are not the agent's to settle — what a paper claims, what is in
scope — and the record could not tell the two apart.

A paper's notebook is where that cost something. The agent laying out the
argument asked *what does this paper claim*, answered it with a claim of its
own — *held to what a working check reads* — and opened eighteen questions
under it. The author never accepted it, and later turned it down in so many
words; two postscripts recorded that. The answer stayed `[answered]`, and its
own line went on reading as settled, ahead of the notes, to anyone who did
not open them. When the drafts kept drifting back to that claim, the
project's own investigation of why named this as one of four routes:
sessions resuming the work read `note_projects` and `note_path` first, as
the machine's instructions say to, and read the claim back as the author's.
That is the project's reading of its own history, one case; it is also the
request this answers.

So an answer says whose it is, on its own line, in every view:

```
Q1  what does this paper claim  [answered, then REJECTED by the user]
Q2  what must be shown for it   [answered, then WITHDRAWN]
Q3  what the author's brief claims  [answered, endorsed by the user]
Q4  why the drafts kept drifting    [answered, not endorsed by the user]
```

- **Not endorsed by the user** is what every answer an agent writes is, and
  it asks nothing of the writer: it is the true state of an answer nobody
  has put to the user. The tally at the top of `note_path` counts each kind.
- **Endorsed by the user** takes their own words, verbatim, and where they
  said them — `note_answer(..., user_said="「1にしよう。」 (chat,
  2026-09-30)")` when they decided it, `note_postscript(label, text,
  answer_is="ENDORSED", user_said=...)` when they accept it later. The user
  is the person the work is for. A message from an agent — the one writing,
  or the one that delegated to it — is not theirs, and a paraphrase is the
  agent's reading of them, recorded as them.
- **Rejected by the user** (`answer_is="REJECTED"`, with their words) and
  **withdrawn** (`answer_is="WITHDRAWN"`, the writer's own finding that it no
  longer stands, with no words of the user's) both mean it no longer stands.

Endorsing and rejecting need the user's words for the reason a note on an
attempt with nothing measured behind it renders as `INTERPRETATION`: a claim
that the user holds something is itself a claim, and it is not free.
Withdrawing needs none — saying an answer no longer stands takes nothing from
anyone that they were entitled to rest on.

**Nothing written is touched.** The answer stays as it was written, with its
date. Each mark is a postscript with its own date; the latest one is where
the answer stands, and every one of them prints. It is a field rather than a
sentence in the note because the code has to act on it, and the two
postscripts on that paper's claim said it no longer stood in sentences.
Nothing reads a postscript's text for words like *replaced*: a row written
before these fields existed reads as not endorsed, which is what it is, and
adding the mark is one more note.

When an answer no longer stands:

- Its question's line says so wherever a question is one line — the map, the
  tree, and the `under` lines of every question opened beneath it.
- `note_trunk` prints where it stands, with the user's words, before the
  answer, and the answer as one line with the call that gives it whole.
  Printed whole, it came to the front ahead of the notes that said it no
  longer stood.
- The CONFIRMED attempts opened under that question leave STANDING for **NO
  LONGER STANDING**. Their verdicts are bound to falsifiers written before
  the data and do not change, but STANDING is read as what to rest on, and
  on that paper two of the hypotheses in it were the rejected claim itself.
  Questions opened below it keep their own answers' standing, each marked
  on its own: on that paper some of the requirements under the claim went
  with it and some did not, and only the people working it can say which.
- A citation of the question, or of an attempt under it, warns, whatever its
  role — it was learned later, like any note. That paper's requirements cited
  the claim's own attempt as support five times.
- `note_open` and `note_search` give where it stands before the answer.

An answered question that was later replaced (`note_ask(supersedes=)`) says
so on its line as well — `[answered, not endorsed by the user, then replaced
by Q5]`. It used to say `[answered]` and nothing more.

## An argument is a tree

A claim is supported by what it requires, and each requirement by what shows
it. Written as a paper, that was sixteen questions: *what does this claim*,
then five requirements under it, then two under each of those — *which
material shows this* and *which section says it*.

The record had no way to say it. `supersedes` means the earlier question was
wrong, so using it for a requirement would be a lie; leaving it off made each
requirement a question related to nothing, and the digest then announced them
as *"the question moved: Q1 → Q2 → … → Q8"* — a project read as one long
reformulation, its earlier questions as abandoned framings, over questions
that had superseded nothing. Nothing stopped the root being answered while a
requirement under it was still open, either. The agent writing that paper
stopped before opening its second question and asked for the shape, because
labels are cited and a flat sixteen cannot be rearranged afterwards.

```
note_ask(project, "what does the claim require", parent="Q1")
```

```
  THE PATH

    Q1  what does this paper claim, in one sentence  [answered, not endorsed by the user]
        ANSWER  (not endorsed by the user) structure decides what an agent can handle, not perception

      Q2  the claim must explain the failures too  [answered, not endorsed by the user]
          A3   CONFIRMED   every failure is a place nothing was written down

        Q4  which material shows that  [became Q7]
        Q7  which material shows it, in the board's own record
```

**The parent cannot be answered while anything under it is open**, at any
depth — the same rule as an open attempt, one level up: an answer written
over a requirement still in flight is a summary, not a conclusion. A
replacement stands where the replaced question stood, so reformulating a
requirement does not move it out from under what required it; `supersedes`
and `parent` therefore cannot be passed together. Nothing opens under a
question that is already settled: its answer is written, and a gate added
afterwards is one that never held.

`note_trunk` prints the line of questions this one serves and the ones
waiting under it, `note_path` indents the tree, and the digest now names only
the reformulations that happened.

## Standing on another project's record

A result or an answer can cite one:

```
note_result(project, "20 of 23 events explained", "CONFIRMED",
            cites="de10nano-4ch-adc/A4, de10nano-4ch-adc/Q4")
```

Prose could already name one, and that is the problem. A name in a sentence
is not checked and does not change when what it names does. A paper's claim
rested on about twenty attempts in a board's notebook; one of them had since
been annotated — the number it reported had come off a rig that was
double-counting — and the citing text went on reading as sound. That is this
record's own failure, an unverified intermediate promoted to a fact, crossing
a project boundary where nothing was watching for it. The same draft had
already cited *"119"* from an article where the registered measurement was
113, and found out only by reading the whole attempt.

So a citation is a row, and what it names is read at the moment the citing
record is read — never stored, never cached:

```
  A1   CONFIRMED    structure decides what an agent can handle
       -> 20 of 23 events explained
       RESTS ON de10nano-4ch-adc/A4: learned later about it (2026-09-15):
                the 113 came off a rig that double-counted courtyards
```

It warns when the cited attempt is open, BLOCKED, FALSIFIED, INCONCLUSIVE or
ABANDONED (none of those is a standing result), when the cited question is
still open or was replaced, when anything has been learned about it since,
and when a reading inside it was reported false.

**The role says which warnings are true of a citation.** `supports` is the
default and leans on the row as a result. `refutes:` leans on a rival
explanation having been *killed* — a FALSIFIED row is the most valuable kind
in this record, and an argument that stands on one is standing on exactly
that — so there FALSIFIED is the sound verdict and CONFIRMED, OPEN or
INCONCLUSIVE is the warning. Filed as a recording instead, it would stop
warning and also stop saying that anything was leaning on it.

**`records:` says you are citing what happened, not leaning on it.** A paper
citing nine attempts as the events it describes — several FALSIFIED, cited
*because* they were falsified — got six warnings back, five of them *"not a
standing result"*, and the note that mattered (the number behind one of them
had turned out to be an artefact) was a line among them. Prefixing a
citation with `records:` drops the verdict warnings for that one and keeps
every warning about what was learned later, which is true either way. The
default is the loud one: you have to say you are only recording. A citation that names no row
is refused: it reads as a reference and cannot be followed. Citations travel
with the record, and one whose target this notebook does not hold is carried
and said, rather than dropped or shown as checked.

## The loop

```
note_trunk(project)        where am I
note_hypothesis(...)       pre-register. Returns hypotheses like this one
                           from EVERY project — settled ones with their
                           verdicts, and any another agent has open now
   ... do the actual work ...
note_result(...)           the numbers, and a verdict
note_ask(..., supersedes=) when the question itself was wrong
note_answer(project, ...)  when it is settled
```

The cross-project search is not a separate tool anyone has to remember:
the only route to recording passes through it. It answers two questions at
once, because they have different consequences:

- `already_tried` — attempts somebody carried to a **verdict**. A FALSIFIED
  row here is days you do not spend.
- `in_flight` — attempts another agent has **open right now**, with their
  falsifier and apparatus. Reported, never refused: two rigs measuring one
  claim is a replication and worth having; the same measurement twice by
  accident is waste, and only the caller can tell which.

## More than one agent

The notebook is shared by every project on the machine, so two agents
writing at once is the ordinary case rather than an exotic one.

**Handing over.** The handover document is the trunk. `note_projects` shows
which projects have an attempt still open; `note_trunk` on one of them shows
the position; `note_open` gives the body. An open attempt prints its
falsifier, its apparatus and how long it has been open — those three *are*
the handover, and they disappear once it closes, because a closed attempt
hands over its result instead. The receiving agent may finish someone
else's attempt with `note_result`, or close it `ABANDONED` if it cannot
reproduce the apparatus named. It may also open an arm of its own beside it
under the same question — but not move on to another question while it is
open, and the question cannot be answered until every arm under it has closed,
so an inherited attempt cannot be quietly left behind.

**Arms of one question, side by side.** A question often has competing
answers worth measuring at once — *the solver is faster vectorised on the
CPU*, *the solver is faster on the GPU* — and a project's agent may hand each
to a helper and run them in parallel. Each is pre-registered on its own, with
its own falsifier, and each is closed by label; with more than one open,
`note_result` and `note_blocked` refuse to guess which one a number belongs
to. The rule that is left is the one that was always doing the work: **the
front is one question.** Attempts open under two questions at once are still
refused, because that is two positions and the trunk shows one. It is one
front *per notebook*: two machines working one project each keep their own,
and the trunk lists the other's open work apart, as `open_on_other_notebooks`
(see the next section).

```
QUESTION Q1  which device makes the solver faster at N=1e6

  A1   OPEN         the solver is faster vectorised on the CPU
       falsifier: CPU median is not below 0.8x the baseline
  A2   OPEN         the solver is faster on the GPU
       falsifier: GPU median is not below 0.8x the baseline
```

Two arms are compared in the end, and they can only be compared if they were
measured the same way. So each new arm gets back the arms already open beside
it — their `measure`, `falsifier` and `apparatus` — at the moment it is
pre-registered, before any number exists rather than after both do. And
`prompted_by` cannot name a sibling: it points at a result that was read, and
an arm in flight has none. The old rule enforced that by itself, and a test
said so, predicting that relaxing it would let an in-flight attempt become an
edge unnoticed; the guard is written out now.

One thing the record cannot see: every attempt reads its commit from the
project's `repo`. An arm whose code lives in another checkout — a git
worktree, which is how parallel helpers usually get one each — is recorded
against that checkout's commit, not its own. `note_hypothesis` says so
whenever an arm opens beside another.

This used to be one open attempt per project, and parallel agents took a
project each. That split one question's arms into records that could not see
each other, which is the failure the notebook exists to stop.

**Working in different projects.** What connects them is `note_hypothesis`,
which searches every project on every write, and `in_flight` in particular:
it exists because two agents can otherwise pre-register the same hypothesis a
minute apart and neither will ever learn it. The other attempt has no
verdict, so prior art cannot mention it, and `note_search` is the one tool
nobody is obliged to call.

**One writer at a time, at the file.** Every guard in the store is a read
that authorises the write after it. Those pairs run inside a single
`BEGIN IMMEDIATE`, with WAL and a busy timeout, so a second agent waits and
then reads what the first one actually wrote. Without that, two agents
opening arms at the same instant are handed the same label, and the rules
above hold for one agent and quietly stop holding for two — which is this
server's own failure mode, arriving through the server.
`tests/test_two_agents.py` fails against a deferred transaction.

## The same project on another machine

The notebook is per machine, so a project worked on from two of them had
two records that could not see each other — and each looked complete, simply
missing the other's work. `note_export` writes one project's record into its
own repository, and `note_import` merges it on the other side:

```
note_export("PcbRouter")          # -> <repo>/.sainpost/PcbRouter.json
  ... commit, push; pull on the other machine ...
note_import("/home/you/work/PcbRouter")   # every .sainpost/*.json there
```

```bash
python -m sainpost.share export PcbRouter [path]
python -m sainpost.share import [--dry-run] <file-or-repo>
```

**Look before you import.** `note_import(path, dry_run=True)` runs the same
merge inside a transaction and rolls it back, so what it reports is what the
import does rather than a forecast of it: which project the file lands in,
what it adds and closes, what it leaves behind, and what it would be refused
for. An agent that asked for this had read the code and opened the database
read-only to work that out by hand, because the only other way to learn what
an import does was to do it — and an import cannot be taken back.

**Import before writing anything to that project, export when you stop.**
Both machines write, in turn, so an import is a merge of two append-only
records — and it can be one only because nothing here is edited. A row
exists or it does not; the only changes to one that exists are one-time
transitions (an attempt closing, a question answered or superseded, a request
decided, a defect queried, replied to or closed), each NULL-to-value, once.
An import adds the rows this notebook lacks and applies the transitions it
has not seen, and overwrites nothing.

**Labels are never renumbered — and a number is not unique.** Labels are
cited inside other records — *"A22 showed"*, *"R3 was accepted on"* — so a
renumbered row silently changes what every sentence pointing at it means. For
a while that was kept by refusing: a question or attempt was matched by its
label, the same label with different contents meant both machines had added
to the project without importing first, and nothing was written. That made
the ordinary way of working — two machines at once, on one investigation — a
refusal every time, and it left the record that was found here: `PcbRouter`
written on one machine and `pcbrouter` on the other, 19 and 40 questions of
one investigation, both numbered from Q1, and nothing that could join them.

So a question or attempt is now what requests and defects had become a
fortnight earlier (below): its number **and what it was made with** — `ident`,
a hash of its text and the moment it was made — and it carries the name of
the notebook that wrote it (`origin`). A notebook names itself the first time
it is opened: three characters, never changed, since they end up in labels
agents copy into text. A number held twice prints bare for the first holder
here and after the writer's name for the other:

```
Q20        is it the frontage          written in this notebook
Q20@k7m    is it the via stack         written in notebook k7m
```

A notebook's own rows print bare in it, so the two machines print the pair
the other way round — and each agent's text, which cites its own work bare,
reads right where it was written. The next number is past every holder, so a
number is only ever shared by rows made before the two notebooks saw each
other. `note_open` on text written elsewhere names the row a bare label in it
meant, the same way as for requests and defects (below).

What is still refused, with nothing written: a row closed differently on
each side; one notebook left open under two questions (one front per
notebook, above); and two projects under one name that are not one project.
That last used to be caught at Q1. With a Q1 able to arrive as `Q1@k7m`, it is
caught at the card: a project is made once and carried, so the same project
has the same card on every machine, to the second and to the word, and a
number both use under two different cards is refused as two investigations.

**Two projects that are one investigation are merged by being told so.**
`note_merge(into, absorbed)` moves every question and attempt of one into the
other and keeps every number. A number both held prints bare for the row
written in this notebook — or else the one `into` held — and after its
notebook's name for the other. The old name is read as the new one from then
on, by every tool and by the import of a file the other machine is still
writing under it. The merge travels: `note_export(into)` names what it
absorbed, and the import on the other machine makes the same merge there,
where that machine's own rows print bare. It is refused where it cannot hold:
a row carried in before files said which notebook wrote it (import the
current export of the machine that wrote it first — rows are matched by what
they are, and their notebook is recorded); a number one notebook used in
both, which that notebook's name cannot tell apart; and one notebook with
work open under a question in each. It is not undone. It says the two were
always one investigation.

**A project is matched by its exact name, or by `rename=`.** The first real
import met the case exact names leave: `PcbRouter`, written on one machine,
arriving where `pcbrouter` already recorded the same checkout. They were two
investigations of one repository — Q1 through Q14 were different questions on
each side — so naming one as the destination of the other could only have
been refused at Q1; making them one project would have meant renumbering
questions and attempts, which nothing then could avoid. Two projects on one
repository are allowed, and were already in the notebook. What was wrong was
that it happened without a word, so the import (and its dry run) says when a
project new here arrives beside one that records the same repository or
differs only in case — and now also when a *side* of its requests or defects
would become a blank card beside such a project.

The second case was different in kind. Trace-from-photos had filed its
requests to `cadbridge`, a blank card its own notebook made by naming it; the
notebook they had to reach knew the tool as `CadBridge`, with eight questions
and twelve attempts. Matched by exact name, every one of those requests would
have gone to a second, empty project. `note_import(path, rename={"cadbridge":
"CadBridge"})` reads the name as the project here — for the file's own card
and for every request and defect naming it as a side. It joins nothing the
checks above would refuse: a card made separately is still refused where the
two use one number, so what it can join is a card with nothing to renumber. The reading is **recorded**, because the other machine goes on
writing its own name, and one import that forgot to say so would file that
machine's next requests under a blank card for good — nothing here is moved
afterwards. So it is refused for a name that is already a project here, and
for one an earlier import was told means something else.

The case matters on disk too. `PcbRouter.json` and `pcbrouter.json` sit side
by side in a Linux checkout, and a Windows or macOS one cannot hold both — git
checks one out over the other, and the loser is a whole record gone from the
machine it was carried to. `note_export` refuses to write beside a file whose
name differs only in case, and asks for `path=`; the import reads the project
from inside the file, so the file's name is free. The one exception is the
file of a project merged into this one: the merged record is its successor,
and goes over it under its name.

`note_export` enforces the order from its side: it will not overwrite a file
that carries records this notebook does not have yet, because that file is
the other machine's work in transit, and replacing it would take that work
back out and guarantee the next write here collides with it.

**R and D labels are notebook-wide, and each machine numbers its own**, so
two machines that each file one request have collided. For a while a
request or defect whose number was taken here was left behind. The pair of
files that ended that carried 32 requests and 13 defects, and the dry run was
going to drop 42 of them — nearly every decision and fix the tool's
repository most needed — while their text, which did come across, cited them:
*"R6 のカメラ読み返しで毎枚確認"* eleven times, about trace-from-photos' own
R6, into a notebook where R6 is a board request.

So a request or defect is its number **and what it was made with** — a hash
of its creation fields (`ident`), the same on every machine, and blind to the
names of its two sides, since `rename=` can read those differently. A record
whose number is held here by another comes across anyway, under the same
number, and prints the hash beside it:

```
R6          footprints を禁止する rule area…      [PcbRouter -> PcbRouter]
R6@1cc456   screenshot の応答に、camera を…       [trace-from-photos -> CadBridge]
```

The record that held a number here first keeps printing it bare, so nothing
already here is ever relabelled, and a new number is never one already taken.
A qualified label is the same on every machine that holds the record; every
tool that takes a label takes one.

**A bare label means whatever the notebook it was written in gave that
number**, so what a bare R6 inside carried text names is worked out where the
text is read, and never by rewriting it. The first file carried also said
*"D4: プランが「0 avoid」と言った…"* about its own D4 — and in that same file
`D4` is a diode's pad (`D4.1`) and a MOSFET's drain (`D4(67.31,49.53)`), and
`R1` a resistor on the gate. A substitution would have corrupted designators
as surely as it fixed citations. Instead the notebook records which writing
arrived from where (`carried`: a row's making, and each one-time transition
— an attempt opened on one machine and closed on the other is the ordinary
handover), and `note_open` on text written elsewhere names, beside it, the
record each bare label meant when that is not the one it names here:

```
"labels in text from another notebook": {
  "R6": "R6@1cc456  screenshot の応答に… [trace-from-photos -> CadBridge]  (in: apparatus, result)"
}
```

A reader who follows the bare label anyway lands on this notebook's R6, and
its body lists the other records under that number. Pad references like
`D4.1` are skipped; no label is ever written that way. It is still string
matching for a reader to judge, and it says so.

It is worked out where the text is read, not as each file arrives, because
the cited record can travel in a different file: trace-from-photos' D4 and
R19 cite R16, which only cadbridge's file carries. Resolved per file, the
answer depended on which file was read first. The import that brings a
record says so for the text an earlier import carried, and the dry run of a
repository's files is now one merge rolled back at the end, so the second
file's report already sees what the first one added. With records from more
than one other notebook under one number, the record cannot tell which of
them wrote a text, and the body says so rather than choosing.

A defect whose stopped measurement
belongs to a project this notebook does not hold says where that attempt
lives instead of claiming nothing was stopped, and a note citing an attempt
that is not here is left behind rather than printed as `INTERPRETATION`.

The position is a pointer each machine moves for itself. The file's is taken
only when this notebook has nothing the file lacks. The repository path is
not carried at all — it names nothing on the other machine; a project new to
this notebook takes the repository the file was found in.

The file is UTF-8 with LF endings and is a pure function of the record: no
timestamp, no host, no local path, so an export that learned nothing leaves
it byte-identical. It is the project's **whole** record, including requests
and defects exchanged with other projects, so committing it to a public
repository publishes all of that. `sainpost-project/1` carried every
reference as a number, which was identity only while numbers were unique in
a project. `/2` carries each question and attempt with its `ident` and its
`origin`, and every reference between them — a parent, a replacement, the
question an attempt is under, what prompted it — as an `ident`. A `/1` file
is still read, by upgrading it in memory; what it cannot say, which notebook
wrote each row, stays unknown until a `/2` file of the same rows says it. A
server older than `/2` refuses a `/2` file rather than misreading it, so the
other machine is updated before it imports one. What the notebook records
about imports (which file, which writing, which name was read as which)
stays in this notebook; it names files on this disk.

It is the one thing the notebook writes into a repository it observes, and
only when asked. The cost is said at export time: **committed while an
attempt is open, the file moves HEAD**, and that attempt closes against a
different commit than it opened on — which the record reports as the code
having moved, on code that did not. Commit it after the attempt closes.

## Which build was actually running

`apparatus` asks for *"the check that the rig is sound: versions, flags,
which build is actually running"*. When the rig is code, prose cannot answer
the last one and a commit id can. Two failures follow from not recording it,
and neither reports an error:

- **The code moves under a measurement.** You pre-register at one commit,
  measure, close at another. The number then reads as a fact about the
  current code and nothing disagrees. Both halves look completely normal.
- **A number is taken while the working tree differs from every commit.** It
  cannot be repeated, so it is not a measurement — but it looks exactly like
  one once written down.

Start a project with a repository and every node records the commit it was
created against, and whether the working tree differed from it:

```bash
note_start("ddr", "escape routing", repo="/home/you/work/router")
```

**The notebook reads and writes nothing.** No commit, no ref, no push,
nothing under `.git` at all — every call carries `--no-optional-locks`, so
not even the index's stat cache is refreshed, and
`test_nothing_under_git_is_written_at_all` fingerprints every file under
`.git` before and after to prove it. A second test walks this module's AST
and fails if any `git` subcommand outside `{rev-parse, status}` appears.

That guard exists because the first version of this feature did the
opposite. It built a tree, wrote a commit, moved a ref and pushed it, so
that a dirty tree could be made reproducible. Every fault it produced came
from that one decision: a working tree pushed off the machine before
anything said so, refs left in repositories the notebook did not own, and —
because a dirty tree got a fresh timestamped commit at each capture —
*"the code moved under this measurement"* firing on byte-identical code,
destroying with its own noise the single signal the mechanism existed to
give. A notebook that modifies what it observes is not a notebook.

The two kinds of difference are reported separately, because they mean
opposite things:

```json
"measured_against": {
  "commit": "8f2a51c66146",
  "untracked files, in no commit": "__pycache__/"
}
```

A **modified tracked file** means the code the number came out of is in no
commit and cannot be returned to. **Untracked files** are listed by name and
not judged — running any Python program creates `__pycache__/`, and an alarm
that fires on that is an alarm that gets ignored, while an untracked file can
equally *be* the experiment. Conflating them made the warning fire on every
Python investigation with a false claim, and one agent passed that claim to
another team inside a defect, telling them they could not reproduce something
they could.

Neither is a task. Committing on your behalf would make the sentence false
without making the number reproducible by anyone else — and a receiving agent
reported the earlier wording as an alarm with no path to ever being satisfied,
since the notebook never commits and its own instructions say to commit only
when asked. `.gitignore` is respected, because git's own `status` respects it.

A project started without `repo=` is not second-class; it simply records no
commit.

**A stale repo path can be re-pointed, and only a stale one.** A path is not
a claim about the world at a moment — which is what everything else here is,
and why none of it can be edited. It is a pointer, and pointers move: the
trial records that found half the faults in this server name commits that
lived in a scratch directory due to be cleaned up. `note_start` on an
existing project with a `repo=` re-points it *if the recorded path no longer
resolves*, and moves nothing else — a path that still exists is refused, and
the description is a claim and stays exactly as written. That narrowness is
the whole guard against this becoming a general edit path.

## When the apparatus breaks and the fix is not yours

An agent implements something, another agent goes to measure with it, and a
trivial bug stops the run. Nothing was measured, so nothing was learned
about the hypothesis — but the four verdicts all say something about it.
`ABANDONED` is [documented as a result about the budget](sainpost/store.py#L55);
a `TypeError` says nothing about the budget. There was no honest way to
close that attempt, and holding it open pins your project's only front to
somebody else's schedule.

`BLOCKED` is that verdict, and it is reachable only through `note_blocked`
with `stopped=true`, which frees the front and files the defect in one call. The two cannot
diverge: an attempt closed blocked with nobody named is a lost day nobody is
working on, and a defect with no stopped measurement behind it is the
wishlist this record has no room for.

**The split is the feature.**

| | the blocked party writes | the owner of the apparatus writes |
|---|---|---|
| | `invocation` — what you ran, verbatim | `cause` — what was actually wrong |
| | `observed` — what came back, verbatim | `change` — what you altered |
| | `needed` — what your measurement needed | `verify` — run this before measuring again |
| | | `invalidates` — do numbers taken through the broken rig still stand |
| **cannot write** | the cause, or the fix — **there is no field** | |

The reporter measured a symptom, not a cause; if it had measured the cause
this would not be somebody else's bug. A cause asserted without a
measurement, handed to the agent that owns the code as its starting point,
is an unverified intermediate promoted to a fact — this record's own failure
mode, crossing an agent boundary. So there is no parameter for one, and
`test_the_reporter_of_a_defect_is_never_offered_a_field_for_the_fix` asserts
that against the advertised schema, because a client fills in what it is
asked for.

Most of what the owner needs is inherited from the attempt and never
restated: which rig (`apparatus`), what was being measured (`measure`), and
why anyone cares (`hypothesis`).

`invalidates` is a closed vocabulary — `NOTHING`,
`EVERY_MEASUREMENT_ON_THIS_RIG` — rather than prose, because it is written on
every fix and prose written on every fix stops being read. It asks about
*other* measurements, never the blocked one: that produced no number, so a
value naming it could not mean anything. It is what stops
a plausible number taken through a broken rig from quietly staying in the
record as a fact.

**The round trip, without a comment thread.** `NOT_ACTIONABLE` comes back
saying what was missing, and the reporter files a *new* defect with
`supersedes=` — a new node with an edge back, the same shape a re-run of a
falsified attempt takes. Nothing is edited here either. `NOT_REPRODUCIBLE`
requires `verify` too: it passing there and failing here means the two rigs
differ, and that difference is itself an apparatus finding.

`note_query` asks the other side one question without closing anything, and
`note_reply` answers it — **either direction**. The owner needs it when the
crash is one line but nothing says what the thing was *supposed* to do; the
reporter needs it because `needed` is a one-shot at filing time and cannot
carry a question only the owner can answer. Exactly one exchange: a second
means the report itself was wrong, and re-filing already covers that. Every
other lever here is a resolution, which left an agent choosing between
`NOT_ACTIONABLE` — untrue, when the defect is actionable and yours — and
silence.

It shipped owner-to-reporter only, on the strength of one agent needing that
direction. The very next agent was the reporter, read the tool's description,
found its own situation named in it, and the door pointed the wrong way.

**`attempt="none"` is the reporter saying no measurement of theirs is
involved** — the bug is in a tool they are using, not measuring with. The
description had promised exactly that and, with arms open side by side, it
could not be said: omitting the label asked *which arm does this close*, and
naming one either closed a measurement the tool had not stopped or filed the
bug as a false reading inside a measurement it had nothing to do with. An
agent with two arms open filed nothing at all, and the bug it was trying to
report — the digest calling eight unrelated questions one reformulation —
waited for a door to be built. The refusal now names the way out where it is
hit.

## Asking for something, as opposed to reporting something broken

`note_request` is for what you want a tool to **do**, from the project that
uses it. Nothing is broken, so it is not a defect and needs no measurement of
anyone's to be stopped. What keeps it from being a wish is `because`: a
defect proves it happened by pasting what came back, and a request has no
output to paste, so the cost of *not* having the thing carries the weight.
*"Writing one at a time is tedious"* is a preference; *"Q1 through Q13 went
in as thirteen separate calls"* is an observation, and it can be checked.

**Naming the shape you want is allowed here**, unlike on a defect. You know
your own need. What stays forbidden everywhere is telling an owner how to fix
something that *broke* — that is a claim about code you do not own, and it
has no field anywhere in this record. Those two were lumped together for a
long time under "no wishlists", and only one of them deserved it.

`note_decide` closes it `ACCEPTED` or `DECLINED` — not the defect vocabulary,
because a request is not broken and cannot be fixed; it is wanted or it is
not. The reason is required either way: declined with none reads as nobody
looked, and accepted with none loses what was actually agreed to, which is
rarely the whole of what was asked. Requests appear beside defects in the
owner's trunk, because what an agent needs is one answer to *what is on my
plate*, not two lists it has to remember to check.

The first one came from another project an hour after this existed, and was
accepted for `note_ask` and refused for `note_hypothesis`: an attempt commits
to a falsifier before the data, and writing several in one call is writing
several commitments nobody has had to stand behind separately.

**A tool that worked and told you something false** belongs here too, not in
`note_request`. Nothing has to have crashed and nothing of yours has to have
stopped: a tool that reports a position which is not the position has done
the worse thing, which is hand back a plausible answer. That is the failure
this record is built on, one level down — and for a while it had no home,
because the only defect path was framed around something breaking. Three
reports arrived as requests for exactly that reason.

**A false reading inside a measurement that went through** stops nothing,
and for a while nothing could say so. `note_blocked` closed whatever attempt
was open as `BLOCKED`, *not measured*. The first false reading to arrive
(R29) was a seam inspection reading a 0.1 mm step as a 138° crease, filed
after seven predictions and a control had all been measured — so the call
that reported it recorded that measurement as one that never happened, for
good, and its numbers could only go back in as a note rendered as
interpretation. Calling `note_result` first was the one order that kept
them, and nothing said so.

So `note_blocked` asks, whenever there is an attempt to touch: `stopped`,
refused until it is answered, because only the reporter knows whether a
number came out and either default is wrong for somebody. `stopped=true`
closes it `BLOCKED`, as before. `stopped=false` files the defect against a
reading inside the attempt and touches nothing else — an open attempt stays
open for `note_result`, a closed one keeps its verdict — so the two calls
can come in either order. The link has its own column, `reading_in`;
`attempt_id` still means only the measurement a defect stopped. It is
printed wherever the verdict is — the trunk, `note_path`, `note_open`, and
beside the falsifier in what `note_result` returns — because a verdict can
rest on the reading: that first one had fired a pre-registered falsifier.

**A bug in a tool you are only using** is the same thing and needs no
measurement of your own to be stopped. That requirement shut out exactly the
reporter who most needs to be heard: a second agent recording an
investigation here had thirteen questions, no attempts, and therefore no way
to report anything about the notebook it was using. What keeps this list from
becoming a wishlist was never that rule — it is `invocation` and `observed`
demanding verbatim text, and *"it would be nice if"* cannot be written into
*"what came back, verbatim"*. Where the reporter was is read from the record
rather than typed.

**Filing against a project nobody has started yet** gives it a blank card,
and its own team fills that in with `note_start` when they arrive. Requiring
the owner to exist first made a reporter run `note_start` for another team:
writing a description of an investigation it knew nothing about, which is
precisely the unverified intermediate this record refuses everywhere else.
Adopting a blank card is not an edit — it is the first time that project's
own team has spoken.

`note_defects()` is the machine-wide list of measurements currently stopped
on somebody. It cannot rot into a backlog: a row exists only while a
specific pre-registered measurement is stopped by it. Both directions also
appear in the trunk — why your front is empty, and whose front you are the
reason for:

```
PROJECT  ddr
QUESTION Q1  why do U2's four byte lanes jam

  A1   BLOCKED      via price is too high to escape to another layer
       -> not measured -- the apparatus failed, see D1

  YOU ARE BLOCKED ON (note_open for the body):
    D1  TypeError: 'NoneType' object is not subscriptable   [router-impl]
```

## Backing it up

The record lives outside this repository, so it is the one thing here with
no second copy. `backup.py` makes one:

```bash
python backup.py              # snapshot, send it off this disk, commit
python backup.py restore      # rebuild the database from the dump
```

`SAINPOST_DRIVE` says where the copy goes — either a directory some sync
client already watches, or an rclone remote like `gdrive:Sainpost`:

```bash
export SAINPOST_DRIVE=gdrive:Sainpost
```

```powershell
[Environment]::SetEnvironmentVariable(
    'SAINPOST_DRIVE', 'C:\Users\me\OneDrive\Sainpost', 'User')
```

**The server runs it after every call that wrote.** Run by hand, it was not
run: for three weeks every copy at the destination was a test fixture — the
suite's backup tests inherited the real `SAINPOST_DRIVE` and sent their
notebook there — and the real one had no copy off its disk. So whether a call
wrote (the connection's `total_changes`, not a list of writing tools) is what
starts `backup.py --no-commit` in the background: one run at a time per
server, writes during it make one more, and a lock keeps two servers from
running it at once. At the destination the new file lands beside the old and
replaces it in one step, so a run stopped partway leaves the copy that was
there. `SAINPOST_AUTOBACKUP=0` turns it off; the tests do, and take the
destination away.

A OneDrive or Dropbox folder is the directory case, and on Windows it starts
with a drive letter — so the two forms both contain a colon, and the whole
difference between them is that a drive letter is one character long.
Deciding on the colon alone told a Windows user that their own backup folder
was *an rclone remote, and rclone is not installed*: an error about a program
they had no reason to have, for a directory that was sitting right there.

**Two files go, and neither is a `cp` of a live notebook.** `research.db` is
a consistent snapshot through sqlite's own backup API — it restores by
copying and is the thing itself. `research.sql` is the same record as text —
readable, greppable, salvageable by hand if the binary is ever damaged, and
the one that diffs if it is in git. Together they are under 150 KB, so
choosing between them buys nothing.

Never `cp` the live `.db` yourself: WAL keeps recent writes in
`research.db-wal`, so the copy opens cleanly and contains nothing. Three
sessions of records were lost here to exactly that, and
`test_the_database_copy_goes_through_sqlites_backup_api` leaves a notebook
open and mid-write to prove the backup does not repeat it.

The send happens on every run, including one where nothing changed: *nothing
to commit* is not *nothing to send*, and a destination that was only just
configured, or that the last run could not reach, is exactly the case that
must not be skipped. An unreachable destination never costs the backup — the
dump is already written locally.

It writes `notebook/research.sql` — a SQL dump, not the `.db` file. The
record is append-only, so its dump is append-only too: each backup adds
lines and changes none. The dump contains no timestamp and no hostname, so a
run that learned nothing produces no commit and no new version.

It is written as UTF-8 with LF endings whichever machine writes it. The
locale is no more part of the database than the hostname is: Python's default
would have given the same record CRLF on Windows, and on a Japanese Windows
the console codepage is cp932, which cannot encode an accented word — a
notebook that had recorded one would have ended the backup with a
`UnicodeEncodeError` rather than a file.

**`notebook/` is gitignored.** The notebook is machine-wide: it carries every
project's investigation on this host, and once a second agent starts using
it, that includes other people's work in flight. That is a scope decision,
not a size one — the measured cost of keeping it in git was single-digit MB
over years.

What that gives up is the ability to say *which backup introduced a
corruption*, so the destination keeps it instead: the copy being replaced is
moved under `history/<date>/` rather than overwritten, and a run that changed
nothing files nothing. Drive's own file versions expire; these do not.

The snapshot is taken through sqlite's own backup API, so it cannot catch a
half-written transaction and cannot block an agent that is writing one.
Restore refuses to land on an existing notebook — there is no update path
anywhere in this record, and that has to hold for the backup too.

**The repository must be private.** The dump is every investigation on the
machine, and a public push is not a mistake anyone gets to take back. The
script asks `gh` before pushing and refuses on a public remote; it also
refuses when it *cannot tell*, which `--push-anyway` overrides. Nothing
overrides a confirmed-public remote.

## Rules the server enforces, and why

| Rule | Why |
|---|---|
| Open attempts all sit under one question; several may run side by side under it | Two open fronts is how position is lost. Arms of one question are one front. `ABANDONED` is a legitimate verdict — a kill criterion firing is a result. |
| With arms side by side, a close names its attempt | Guessing would record one arm's number against the other. |
| `falsifier` and `apparatus` required before measuring | Most lost days are a stale or misconfigured rig producing plausible numbers. Both fields are written while you are still clear-headed. |
| Attempts close once, never edited | If the finding changed, open a new attempt and point `prompted_by` at the old one. The path is the value. |
| A question cannot be answered with work open under it — an attempt, or a question opened under it at any depth | An answer that skips an unclosed front is a summary, not a conclusion. |
| An answer is the user's only with their own words, verbatim; every other answer shows as not endorsed by the user | An agent's answer read back as the author's claim moved a paper away from what its author had said, one resumed session at a time. That the user holds something is a claim, and it is not free. |
| A note can say an answer no longer stands; what was confirmed under it then leaves STANDING | Said in a sentence, the correction sat under an answer whose own line still read as settled, and the next agent cited the answer again. |
| A citation names a row or is refused, and is read as the cited record stands now; the role decides which verdict warns, never whether a later note does |
| A body longer than one line carries a headline, written with it | Every view but `note_open` shows a node as one line. Cut by machine, that line is a summary nobody checked — and it cut a 97-character Japanese question down to "[R1]". |
| A write hands back the check, not the writing | `note_result` returns the falsifier you committed to — that is what the call is for — and the number of characters it stored. Echoing the result cost a copy of everything just measured: the median result here is 1,362 characters, the median falsifier 208, and one afternoon of writes was returning over ten thousand characters a call. | A name in prose is not checked and does not change when what it names does. A draft cited a number that the attempt behind it had already been annotated as an artefact. |
| `why_now` is required once the project has a RESULT to name | Not "from the second attempt on", which is what the field said: an arm opened beside the first attempt is a second attempt with nothing measured, and the agent in that position wrote the paragraph the rule exists to prevent. A client fills in what it is asked for, so the advertised rule is the rule. |
| Guard and write share one `BEGIN IMMEDIATE` | Otherwise the rules above hold for one agent and quietly stop holding for two. |
| `BLOCKED` is unreachable from `note_result`, and needs a defect naming an owner | A front closed as blocked with nobody named is a lost day nobody is working on. |
| `note_blocked` touches no attempt until `stopped` says what the failure did to it | Assumed, it closed a finished measurement as unmeasured, for good, because one reading in it was false. Only the reporter knows whether a number came out. |
| A request or defect is its number and what it was made with; the first to hold a number here prints it bare | Each machine numbers its own, so numbers collide as a matter of course. Left behind, 42 of 45 records in one pair of files would not have arrived; renumbered, every sentence citing them would change meaning. |
| Carried text is never rewritten; what its bare labels name is shown beside it | A bare label means what the writer's notebook gave that number. In a circuit record R1 or D4 is as often a part, so a substitution corrupts designators as surely as it fixes citations. |
| The code state is read, never typed | An agent asserting which commit it measured is a claim. `git` answering is an observation. |
| The notebook writes nothing to the repository it observes | A record that modifies its subject is not a record. Every fault the capturing version produced came from that one decision. The one exception is `note_export`'s file, written only when asked, and it says what committing it mid-attempt costs. |
| A defect's reporter has no field for the cause | It measured a symptom. A cause asserted without a measurement, acted on by someone else, is this record's failure mode crossing an agent boundary. |

A `FALSIFIED` row is the most valuable kind in here. It is what stops the
next session spending days on something that looks like it obviously should
work.

## Tests

```bash
.venv/bin/python -m pytest tests -q
```

`tests/test_code_state.py` runs against real git repositories — a capture
that works against a mock is not evidence about anything, since the whole
mechanism is git's behaviour. `tests/test_defects.py` guards the split between what the blocked party may
write and what only the owner may. `tests/test_two_agents.py` runs two
connections at a barrier; it fails if the
guards are read outside the write lock. `tests/test_the_door.py` drives
`launch.py` over real stdio JSON-RPC and
checks the JSON schema each tool advertises. It exists because every tool in
this server once shipped broken while 41 in-process tests passed: calling a
decorated function directly skips schema validation, so a wrapper that
flattened the signature to `(*a, **kw)` was invisible from inside. Those
three tests fail against that version. A suite that never opens the door
does not test the door.

## Deliberately not built

- **Free-form observations.** Side findings go in `result` or in the
  question's answer. A general notes field becomes the dumping ground that
  the trunk then has to filter, and the trunk's whole value is being small.
  A defect is not an exception to this: it has no body and no comment
  thread, only named fields, each refused when blank. One vague field is
  how a bug report arrives unactionable — which is the same failure as one
  vague word in a conversation, and costs the same round trip.
- **A backlog.** `note_defects` looks like an issue list and is not one:
  nothing can be filed that is not stopping a pre-registered measurement
  right now. Ideas for later have a home already — an open question with no
  attempts under it, which the record has always allowed to stay open
  indefinitely.
- **Editing.** There is no correction path by design. A correction is a new
  attempt with an edge back.
- **Full-text search.** Character-bigram similarity in Python instead:
  FTS5's default tokenizer turns an entire Japanese sentence into one token,
  and at this scale the ranking is better off being a number someone chose.

## License

MIT — see [LICENSE](LICENSE).

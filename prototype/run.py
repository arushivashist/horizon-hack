"""First-hour test: the notebook agent vs. an auto-summarize baseline on the same on-call days.

  python3 gen.py                                                          # writes data/
  uv run --with anthropic --with duckdb python run.py --fake              # plumbing check, no API calls
  uv run --with anthropic --with duckdb python run.py --env-file PATH     # real run; key read from PATH

Both agents get the same model, tools, query budget and pages. Only memory differs:
- baseline: one conversation for the whole run. Past COMPACT_AT tokens it is replaced by the
  model's own summary, written with a strong prompt so the baseline isn't a straw man.
- notebook: every call starts blank and sees only MEMORY (lessons it curates itself), the
  current page, its incident notebook, and its last tool result.
"""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import anthropic
import duckdb

HERE = Path(__file__).parent
DATA = HERE / "data"
MODEL = os.environ.get("MODEL", "claude-opus-5")
FALLBACK_MODEL = "claude-opus-4-8"
PRICE_IN, PRICE_OUT = 5.0, 25.0  # $/MTok for claude-opus-5; cache writes cost 1.25x input, reads 0.1x
MAX_QUERIES = 15  # per page
MAX_CALLS = 25  # model calls per page, a safety stop
ROW_LIMIT = 50
RESULT_CHARS = 4000
COMPACT_AT = int(os.environ.get("COMPACT_AT", "30000"))  # baseline context size (tokens) that triggers a summary
ENTRY_CHARS = 400  # per memory entry
LESSON_SLOTS, NOISE_SLOTS = 12, 3  # noise gets its own small section so it can't crowd out lessons
NOTEBOOK_CHARS = 2000
COST_CAP = float(os.environ.get("COST_CAP", "15"))  # dollars per agent
TABLES = ["metrics", "logs", "deploys", "config_changes", "alerts"]

SYSTEM = """You are the on-call engineer for ShopCo, an online store, during a multi-week rotation.

Services: web calls checkout and search. checkout calls payments (which calls an outside payment provider) and inventory. payments and inventory use Postgres; search uses Redis.

You get woken for pages. Investigate with SQL (DuckDB dialect) over these tables; data exists only up to the current time:
- metrics(ts, service, rps, error_rate, p99_ms, db_conn_in_use, cache_hit_rate, cpu_pct): one row per service per minute, including postgres and redis.
- logs(ts, service, level, message): WARN and ERROR lines plus a few INFO lines.
- deploys(event_id, ts, service, version, author, message)
- config_changes(event_id, ts, service, key, old_value, new_value, author)
- alerts(alert_id, ts, alert_name, service, state, value): state is firing or resolved.

Then close the page: resolve it with the event_id (from deploys or config_changes) that caused it, or dismiss it if it is not a real problem. You get at most 15 queries per page and each returns at most 50 rows, so aggregate (GROUP BY, date_trunc) rather than dumping rows. Stop investigating once the evidence is clear."""

BASELINE_SYSTEM = SYSTEM + """

This conversation runs across your whole rotation: earlier pages and end-of-day handoff notes appear above. When it gets long, older parts are replaced by your own summary."""

NOTEBOOK_SYSTEM = SYSTEM + """

You have no memory of earlier conversations. What you learned on past shifts is in MEMORY, which you maintain yourself. During a page you see only your NOTEBOOK and the result of your last tool call; earlier results are gone. So every query call carries your full updated notebook: hypotheses marked open, confirmed or ruled out, each with its evidence, including what the last result showed."""

HYBRID_SYSTEM = SYSTEM + """

You have no memory of earlier pages except MEMORY, which you maintain yourself and which is shown at the start of each page. Within a page you see everything you have done so far. After you close a page you will be asked to update MEMORY; then the page's conversation is discarded."""

SUMMARY_PROMPT = """Your context is about to be cleared. Write the summary you will keep in its place. Include, for every page so far: the symptom, the root cause you found (with event ids), and what you ruled out and why. Also include recurring patterns and which checks paid off, alerts that turned out to be noise and how you recognized them, and anything from handoff notes that may matter later. Be specific; this summary is all you will keep. Reply with the summary text only."""

EDIT_RULES = f"""Edit MEMORY for future shifts with add_entry, update_entry and retire_entry, then call done; you can make several edits and call done in one reply. Keep only what a query can't give back. A lesson says: the symptom, what to check first, which pages confirmed it, and its status (active, or fixed on day N). A noise entry says: a known false alarm and how to recognize it. Don't copy raw query output. Each entry is at most {ENTRY_CHARS} characters; there are {LESSON_SLOTS} lesson slots and {NOISE_SLOTS} noise slots."""


def tool(name, description, **props):
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {k: v if isinstance(v, dict) else {"type": "string", "description": v} for k, v in props.items()},
            "required": list(props),
            "additionalProperties": False,
        },
    }


QUERY_DESC = "Run one read-only DuckDB SELECT over the telemetry tables."
QUERY = tool("query", QUERY_DESC, sql="The SQL query.")
QUERY_NB = tool("query", QUERY_DESC, sql="The SQL query.",
                notebook=f"Your full updated incident notebook, at most {NOTEBOOK_CHARS} characters.")
RESOLVE = tool("resolve", "Close the page as a real incident caused by one deploy or config change.",
               cause_event_id="The event_id (dep-... or cfg-...) that caused it.", summary="One or two sentences of evidence.")
DISMISS = tool("dismiss", "Close the page as not a real problem (expected behavior or noise).", reason="Why it is not a real problem.")
EDIT_TOOLS = [
    tool("add_entry", "Add one entry to MEMORY.",
         section={"type": "string", "enum": ["lesson", "noise"], "description": "lesson, or noise for a known false alarm."},
         text=f"The entry, at most {ENTRY_CHARS} characters."),
    tool("update_entry", "Replace the text of one MEMORY entry.", id="The entry id, e.g. L2.",
         text=f"The new text, at most {ENTRY_CHARS} characters."),
    tool("retire_entry", "Remove one MEMORY entry that is wrong, fixed or no longer useful.", id="The entry id.",
         reason="Why it is being retired."),
    tool("done", "Finish editing MEMORY.", summary="What changed, in a few words, or 'no change'."),
]
EDIT_NAMES = {"add_entry", "update_entry", "retire_entry"}


class World:
    """The telemetry database, with every table cut off at the simulated 'now'."""

    def __init__(self):
        self.db = duckdb.connect()
        for t in TABLES:
            self.db.execute(f"CREATE TABLE raw_{t} AS SELECT * FROM read_csv_auto('{DATA / (t + '.csv')}', header=true)")
        self.db.execute("SET enable_external_access = false")
        self.db.execute("SET lock_configuration = true")

    def set_now(self, now):
        for t in TABLES:
            self.db.execute(f"CREATE OR REPLACE TEMP VIEW {t} AS SELECT * FROM raw_{t} WHERE ts <= TIMESTAMP '{now}'")

    def query(self, sql):
        s = sql.strip().lower()
        if not s.startswith(("select", "with")) or "raw_" in s:
            return "error: only SELECT queries over metrics, logs, deploys, config_changes and alerts are allowed"
        try:
            cur = self.db.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(ROW_LIMIT + 1)
        except duckdb.Error as e:
            return f"error: {e}"
        lines = ["\t".join(cols)] + ["\t".join("" if v is None else str(v) for v in r) for r in rows[:ROW_LIMIT]]
        if len(rows) > ROW_LIMIT:
            lines.append(f"(only the first {ROW_LIMIT} rows are shown)")
        out = "\n".join(lines)
        return out if len(out) <= RESULT_CHARS else out[:RESULT_CHARS] + "\n(truncated)"


def run_query(world, inp, used):
    if used >= MAX_QUERIES:
        return "error: this page's query budget is used up; resolve or dismiss now", used
    return f"{world.query(inp['sql'])}\n(queries used this page: {used + 1} of {MAX_QUERIES})", used + 1


class LLM:
    """Calls the model for one agent and keeps its token and cost totals."""

    def __init__(self, client):
        self.client = client
        self.calls = self.tokens_in = self.tokens_out = self.max_context = self.last_context = 0
        self.cost = 0.0

    def __call__(self, system, messages, tools, cache_history=False, tool_choice=None):
        if self.cost > COST_CAP:
            raise RuntimeError(f"cost cap of ${COST_CAP} reached")
        extra = {}
        if cache_history:  # append-only history, so caching it is what a real deployment would do
            extra["cache_control"] = {"type": "ephemeral"}
        if tool_choice:
            extra["tool_choice"] = tool_choice
        resp = self.client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            tools=tools,
            betas=["server-side-fallback-2026-06-01"],
            fallbacks=[{"model": FALLBACK_MODEL}],
            **extra,
        )
        u = resp.usage
        written, read = u.cache_creation_input_tokens or 0, u.cache_read_input_tokens or 0
        self.last_context = u.input_tokens + written + read
        self.max_context = max(self.max_context, self.last_context)
        self.calls += 1
        self.tokens_in += self.last_context
        self.tokens_out += u.output_tokens
        self.cost += (u.input_tokens * PRICE_IN + written * PRICE_IN * 1.25 + read * PRICE_IN * 0.1
                      + u.output_tokens * PRICE_OUT) / 1e6
        return resp


def page_text(w):
    fired = "\n".join(f"- {a['ts'][11:16]} {a['name']} on {a['service']} (value {a['value']})"
                      for a in w["alerts"] if a["ts"] <= w["now"])
    return f"Page {w['page_id']}, {w['when']}. It is now {w['now'][:16]}. Alerts firing:\n{fired}"


class Baseline:
    name = "baseline"

    def __init__(self, llm, world, compact_at):
        self.llm, self.world, self.compact_at = llm, world, compact_at
        self.messages = []
        self.pending = []  # blocks for the next user turn: last tool results, handoff notes, the page
        self.summaries = []

    def handoff(self, w):
        self.pending.append({"type": "text", "text": w["text"]})

    def page(self, w):
        if self.messages and self.llm.last_context > self.compact_at:
            self.compact()
        self.world.set_now(w["now"])
        self.pending.append({"type": "text", "text": page_text(w)})
        self.steps, queries = [], 0
        for _ in range(MAX_CALLS):
            self.messages.append({"role": "user", "content": self.pending})
            resp = self.llm(BASELINE_SYSTEM, self.messages, [QUERY, RESOLVE, DISMISS], cache_history=True)
            self.messages.append({"role": "assistant", "content": resp.content})
            results, outcome = [], None
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                self.steps.append([b.name, b.input])
                if b.name == "query":
                    out, queries = run_query(self.world, b.input, queries)
                else:
                    outcome = outcome or (b.name, dict(b.input))
                    out = "page closed"
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            self.pending = results or [{"type": "text", "text": "Continue by calling query, resolve or dismiss."}]
            if outcome:
                return outcome, queries
        return ("timeout", {}), queries

    def compact(self):
        self.messages.append({"role": "user", "content": self.pending + [{"type": "text", "text": SUMMARY_PROMPT}]})
        resp = self.llm(BASELINE_SYSTEM, self.messages, [QUERY, RESOLVE, DISMISS],
                        cache_history=True, tool_choice={"type": "none"})
        summary = "".join(b.text for b in resp.content if b.type == "text")
        self.summaries.append(summary)
        self.messages = []
        self.pending = [{"type": "text", "text": "Summary of your earlier on-call history (older context was cleared):\n" + summary}]

    def extras(self):
        return {"compactions": len(self.summaries), "summaries": self.summaries}


class Notebook:
    name = "notebook"
    system, rules = NOTEBOOK_SYSTEM, EDIT_RULES

    def __init__(self, llm, world):
        self.llm, self.world = llm, world
        self.entries = {}  # id -> {"section": "lesson" | "noise", "text": ...}
        self.next_id = {"lesson": 1, "noise": 1}
        self.memory_log = []  # every edit session, for replaying what it believed when
        self.edit_errors = []  # edits the harness refused; the agent saw each one, and they're kept here too

    def memory(self):
        lines = []
        for section, title, slots in (("lesson", "LESSONS", LESSON_SLOTS), ("noise", "KNOWN NOISE", NOISE_SLOTS)):
            items = [f"[{k}] {e['text']}" for k, e in self.entries.items() if e["section"] == section]
            lines += [f"{title} ({len(items)} of {slots} slots):"] + (items or ["(none)"])
        return "\n".join(lines)

    def page(self, w):
        self.world.set_now(w["now"])
        self.steps, queries, notebook, last, nudge = [], 0, "", "(none yet)", ""
        for _ in range(MAX_CALLS):
            prompt = (f"MEMORY (from past shifts):\n{self.memory()}\n\nCURRENT PAGE:\n{page_text(w)}\n\n"
                      f"NOTEBOOK:\n{notebook or '(empty)'}\n\nLAST ACTION AND RESULT:\n{last}{nudge}")
            resp = self.llm(NOTEBOOK_SYSTEM, [{"role": "user", "content": prompt}], [QUERY_NB, RESOLVE, DISMISS])
            calls = [b for b in resp.content if b.type == "tool_use"]
            nudge = "" if calls else "\n\nYou must call query, resolve or dismiss."
            results = []
            for b in calls:
                self.steps.append([b.name, b.input])
                if b.name == "query":
                    notebook = b.input["notebook"][:NOTEBOOK_CHARS]
                    out, queries = run_query(self.world, b.input, queries)
                    results.append(f"query: {b.input['sql']}\nresult:\n{out}")
                else:
                    outcome = (b.name, dict(b.input))
                    self.reflect(w, outcome, notebook)
                    return outcome, queries
            if results:
                last = "\n\n".join(results)
        return ("timeout", {}), queries

    def reflect(self, w, outcome, notebook):
        kind, args = outcome
        verdict = (f"resolved, cause {args['cause_event_id']}: {args['summary']}" if kind == "resolve"
                   else f"dismissed: {args['reason']}")
        self.edit_memory(f"You just closed page {w['page_id']} ({w['when']}) as {verdict}\n\n"
                         f"FINAL NOTEBOOK (about to be deleted):\n{notebook or '(empty)'}\n\n"
                         f"MEMORY:\n{self.memory()}\n\n{self.rules}", w["start"])

    def handoff(self, w):
        self.edit_memory(f"{w['text']}\n\nMEMORY:\n{self.memory()}\n\nReview MEMORY against today's changes: "
                         f"does anything confirm, fix or invalidate an entry? {self.rules}", w["ts"])

    def edit_memory(self, prompt, when):
        self.edit_loop([{"role": "user", "content": prompt}], EDIT_TOOLS, when)

    def edit_loop(self, messages, tools, when, cache_history=False):
        edits, errors = [], False
        for _ in range(6):
            resp = self.llm(self.system, messages, tools, cache_history=cache_history)
            calls = [b for b in resp.content if b.type == "tool_use"]
            if not calls:
                break
            results, errors, finished = [], False, False
            for b in calls:
                if b.name == "done":
                    out = "ok"
                elif b.name in EDIT_NAMES:
                    out = self.apply(b.name, b.input)
                else:
                    out = "error: the page is closed; only memory edits and done are allowed now"
                finished |= b.name == "done"
                if out.startswith("error"):
                    errors = True
                    self.edit_errors.append({"when": when, "tool": b.name, "input": b.input, "error": out})
                elif b.name != "done":
                    edits.append([b.name, b.input])
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            if finished and not errors:
                break
            messages += [{"role": "assistant", "content": resp.content}, {"role": "user", "content": results}]
        if errors:
            print(f"[{self.name}] memory edit at {when} ended with a refused edit; see edit_errors", flush=True)
        if edits:
            self.memory_log.append({"when": when, "edits": edits, "memory": self.memory()})

    def apply(self, name, inp):
        text = inp.get("text", "")
        if len(text) > ENTRY_CHARS:
            return f"error: that entry is {len(text)} characters; the limit is {ENTRY_CHARS}. Shorten it."
        if name == "add_entry":
            section, slots = inp["section"], LESSON_SLOTS if inp["section"] == "lesson" else NOISE_SLOTS
            if sum(e["section"] == section for e in self.entries.values()) >= slots:
                return f"error: the {section} section is full ({slots} of {slots}). Retire or merge an entry first."
            key = f"{'L' if section == 'lesson' else 'N'}{self.next_id[section]}"
            self.next_id[section] += 1
            self.entries[key] = {"section": section, "text": text}
            return f"added {key}"
        if inp["id"] not in self.entries:
            return f"error: there is no entry {inp['id']}"
        if name == "update_entry":
            self.entries[inp["id"]]["text"] = text
            return f"updated {inp['id']}"
        del self.entries[inp["id"]]
        return f"retired {inp['id']}"

    def extras(self):
        return {"memory": self.memory(), "memory_log": self.memory_log, "edit_errors": self.edit_errors}


class Hybrid(Notebook):
    """Full history within a page; only MEMORY carries across pages."""

    name = "hybrid"
    system = HYBRID_SYSTEM
    rules = EDIT_RULES + " Only record what a page you investigated confirmed; no guesses or watch lists."

    def page(self, w):
        self.world.set_now(w["now"])
        tools = [QUERY, RESOLVE, DISMISS] + EDIT_TOOLS  # one stable tool list, so the page's history caches
        messages = [{"role": "user", "content": f"MEMORY (from past shifts):\n{self.memory()}\n\n{page_text(w)}"}]
        self.steps, queries = [], 0
        for _ in range(MAX_CALLS):
            resp = self.llm(self.system, messages, tools, cache_history=True)
            messages.append({"role": "assistant", "content": resp.content})
            results, outcome = [], None
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                self.steps.append([b.name, b.input])
                if b.name == "query":
                    out, queries = run_query(self.world, b.input, queries)
                elif b.name in ("resolve", "dismiss"):
                    outcome = outcome or (b.name, dict(b.input))
                    out = "page closed"
                else:
                    out = "error: close the page first; you will edit MEMORY right after"
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            if outcome:
                messages.append({"role": "user", "content": results + [{"type": "text", "text": f"Page closed. {self.rules}"}]})
                self.edit_loop(messages, tools, w["start"], cache_history=True)
                return outcome, queries
            messages.append({"role": "user", "content": results or [{"type": "text", "text": "Continue by calling query, resolve or dismiss."}]})
        return ("timeout", {}), queries


def score(w, outcome):
    kind, args = outcome
    truth = w["truth"]
    if truth["type"] == "noise":
        return "correct" if kind == "dismiss" else "false alarm"
    if kind != "resolve":
        return "missed" if kind == "dismiss" else kind
    got = args["cause_event_id"].strip()
    return "correct" if got == truth["cause_event_id"] else "decoy" if got == truth["decoy_event_id"] else "wrong"


def run(agent, wakeups):
    pages, error, llm = [], None, agent.llm
    try:
        for w in wakeups:
            if w["kind"] == "handoff":
                agent.handoff(w)
                continue
            before = (llm.tokens_in, llm.tokens_out, llm.cost, llm.calls)
            outcome, queries = agent.page(w)
            row = {"page_id": w["page_id"], "when": w["when"], "truth": w["truth"]["type"], "action": outcome[0],
                   "answer": outcome[1].get("cause_event_id") or outcome[1].get("reason", ""),
                   "result": score(w, outcome), "queries": queries, "calls": llm.calls - before[3],
                   "tokens_in": llm.tokens_in - before[0], "tokens_out": llm.tokens_out - before[1],
                   "cost": round(llm.cost - before[2], 4), "steps": agent.steps}
            pages.append(row)
            print(f"[{agent.name}] {row['page_id']} ({w['when']}) {row['truth']}: {row['action']} "
                  f"{row['answer'][:50]!r} -> {row['result']}, {queries} queries, {row['tokens_in']:,} tokens in", flush=True)
    except Exception as e:  # keep what finished, so a failure late in a paid run isn't wasted
        error = repr(e)
        print(f"[{agent.name}] stopped: {error}", flush=True)
    totals = {"pages": len(pages), "correct": sum(r["result"] == "correct" for r in pages),
              "queries": sum(r["queries"] for r in pages), "calls": llm.calls, "tokens_in": llm.tokens_in,
              "tokens_out": llm.tokens_out, "max_context": llm.max_context, "cost": round(llm.cost, 2)}
    result = {"model": MODEL, "totals": totals, "error": error, "pages": pages, **agent.extras()}
    (HERE / "results" / f"{agent.name}.json").write_text(json.dumps(result, indent=1, default=str))
    return result


def report(results):
    names = list(results)
    by_page = {n: {r["page_id"]: r for r in results[n]["pages"]} for n in names}
    ids = sorted({pid for n in names for pid in by_page[n]})
    print(f"\n{'page':6} {'truth':9}" + "".join(f"{n:>38}" for n in names))
    for pid in ids:
        truth = next(by_page[n][pid]["truth"] for n in names if pid in by_page[n])
        cells = [f"{r['result']} {r['queries']}q {r['tokens_in'] / 1000:.1f}k ${r['cost']:.2f}"
                 if (r := by_page[n].get(pid)) else "-" for n in names]
        print(f"{pid:6} {truth:9}" + "".join(f"{c:>38}" for c in cells))
    print()
    for n in names:
        t = results[n]["totals"]
        extra = f", summaries {results[n]['compactions']}" if "compactions" in results[n] else ""
        print(f"{n}: {t['correct']}/{t['pages']} correct, {t['queries']} queries, {t['calls']} model calls, "
              f"{t['tokens_in']:,} input tokens, largest context {t['max_context']:,}, ${t['cost']:.2f}{extra}")


class FakeClient:
    """Stands in for the API so --fake can exercise both loops without spending anything."""

    def __init__(self):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))
        self.n = 0

    def call(self, name, **inp):
        return SimpleNamespace(type="tool_use", id=f"toolu_{self.n}", name=name, input=inp)

    def create(self, messages, tools, tool_choice=None, **_):
        self.n += 1
        last = messages[-1]["content"]
        blocks = last if isinstance(last, list) else [{"type": "text", "text": last}]
        tail = blocks[-1].get("text", "") if isinstance(blocks[-1], dict) else ""
        if tool_choice == {"type": "none"}:
            content = [SimpleNamespace(type="text", text="fake summary")]
        elif "Edit MEMORY" in tail:
            content = [self.call("add_entry", section="lesson", text=f"fake lesson {self.n}"), self.call("done", summary="fake")]
        elif "(none yet)" in tail or ("Page p-" in tail and "LAST ACTION" not in tail):
            content = [self.call("query", sql="SELECT service, max(p99_ms) AS worst FROM metrics GROUP BY 1 ORDER BY 2 DESC",
                                 notebook="- fake note")]
        elif self.n % 2:
            content = [self.call("resolve", cause_event_id="cfg-004", summary="fake")]
        else:
            content = [self.call("dismiss", reason="fake")]
        usage = SimpleNamespace(input_tokens=len(json.dumps(messages, default=str)) // 4, output_tokens=40,
                                cache_creation_input_tokens=0, cache_read_input_tokens=0)
        return SimpleNamespace(content=content, usage=usage, stop_reason="tool_use")


def load_key(path):
    for line in Path(path).expanduser().read_text().splitlines():
        line = line.strip().removeprefix("export ").strip()
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip("'\"")
            return
    raise SystemExit(f"ANTHROPIC_API_KEY not found in {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="no API calls; exercises the plumbing")
    ap.add_argument("--env-file", help="read ANTHROPIC_API_KEY from this file")
    ap.add_argument("--agent", choices=["both", "baseline", "notebook", "hybrid"], default="both")
    args = ap.parse_args()
    if args.env_file:
        load_key(args.env_file)
    wakeups = json.loads((DATA / "wakeups.json").read_text())
    (HERE / "results").mkdir(exist_ok=True)

    def one(name):
        # Pin the real API so the key never goes to a proxy that ANTHROPIC_BASE_URL might point at.
        client = FakeClient() if args.fake else anthropic.Anthropic(base_url="https://api.anthropic.com")
        llm, world = LLM(client), World()
        if name == "baseline":
            agent = Baseline(llm, world, 3000 if args.fake else COMPACT_AT)
        else:
            agent = {"notebook": Notebook, "hybrid": Hybrid}[name](llm, world)
        return name, run(agent, wakeups)

    names = ["baseline", "notebook"] if args.agent == "both" else [args.agent]
    with ThreadPoolExecutor(len(names)) as pool:
        results = dict(pool.map(one, names))
    report(results)


if __name__ == "__main__":
    main()

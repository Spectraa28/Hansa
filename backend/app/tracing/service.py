"""Turn recorded runs and agent jobs into Neatlogs traces, and read them back per owner.

Coverage is stated in every trace: model calls come from the gateway ledger and outside
connections from the egress sidecar. Time between model calls is the target's own code and
tools; it is recorded as an inferred gap, never as a measured tool call.

Our database stays the record of cost. Neatlogs does not price the LiteLLM aliases, so each
trace carries the LiteLLM-reported cost in hansa.* attributes and metadata.
"""
from datetime import datetime, timezone
import json
import time

from fastapi import HTTPException

from ..gateway.shape import redact, repeated_prefix
from .neatlogs import NeatlogsClient, NeatlogsError

MAX_SPANS = 300
# The ingest endpoint's request filter scores words such as "count" and "char" and refuses a request at
# roughly fifty of them (measured October 11). Each model span needs two token_count attributes, so
# attribute names here avoid those words and longer traces are sent in parts.
MODEL_SPANS_PER_TRACE = 10
GAP_MS = 100
COVERAGE = ("Model calls are measured at the gateway. HTTP(S) connections are measured at the egress proxy. "
            "Gaps between model calls are inferred time in the agent's own code and tools.")


# How much of a tool step's input and output is kept for the trace panel.
STEP_TEXT = 800
# These return the imported repository's own text. Source stays in the snapshot, out of the database,
# so only the size of what came back is recorded.
SOURCE_TOOLS = {"read_file", "search_code", "list_files", "show_diff", "edit_file", "write_file", "write_adapter"}


def step_output(step):
    if step["name"] in SOURCE_TOOLS:
        text = step["output"] if isinstance(step["output"], str) else json.dumps(step["output"], default=str)
        return f"{len(text):,} characters returned from the repository (not stored)."
    return redact(step["output"], STEP_TEXT)


def step_input(step):
    if step["name"] in {"edit_file", "write_file", "write_adapter"}:
        # The arguments carry the new file text; keep the path alone.
        try:
            path = json.loads(step["input"]).get("path")
        except (ValueError, AttributeError, TypeError):
            path = None
        return json.dumps({"path": path}) if path else "(file text not stored)"
    return redact(step["input"], STEP_TEXT)

def iso(milliseconds):
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def marker(import_id):
    # One unhyphenated token so keyword search can find every trace of an import.
    return "hansaimport" + import_id.replace("-", "")


# Neatlogs prices a trace from each call's model name and token counts; it ignores any cost we send. The gateway's
# short names are not in its price list, so each is sent under the name Neatlogs recognises (checked by reading
# back labelled test traces on 12 October 2026). Its figure is list price; Hansa's own is the provider's per-call cost.
PRICED_NAMES = {"claude-sonnet-4.6": "anthropic/claude-sonnet-4.6", "claude-opus-4.6": "anthropic/claude-opus-4.6",
                "claude-haiku": "anthropic/claude-haiku-4.5"}


def llm_spans(calls, prefix="llm"):
    spans, previous = [], {}
    for row in calls:
        if row["started_at_ms"] is None:
            continue
        shape = json.loads(row["request_shape"] or "{}")
        output = json.loads(row["response_shape"] or "{}")
        repeated, repeated_chars = repeated_prefix(previous, shape)
        previous = shape
        latency = row["latency_ms"] or 0
        last = shape.get("last_message") or {}
        # Worded without "characters" or "count": the ingest filter scores those words and refuses long traces.
        described = (f"{shape.get('messages', 0)} messages, size {shape.get('prompt_chars', 0)}; "
                     f"{repeated} messages (size {repeated_chars}) repeat the previous call.")
        if last:
            described += f" Last {last.get('role')}: {last.get('preview')}"
        served = row["upstream_model"] or row["model"]
        attributes = {"neatlogs.llm.model_name": PRICED_NAMES.get(served, served), "hansa.served_model": served,
                      "neatlogs.input.value": described,
                      "neatlogs.output.value": output.get("preview") or f"{output.get('output_chars', 0)} characters",
                      "hansa.requested_model": row["model"], "hansa.http_status": row["http_status"],
                      "hansa.cost_usd": row["estimated_cost_usd"] if row["estimated_cost_usd"] is not None else "unknown",
                      "hansa.cost_source": row["cost_source"] or "unknown",
                      "hansa.messages": shape.get("messages", 0), "hansa.prompt_size": shape.get("prompt_chars", 0),
                      "hansa.repeated_messages": repeated, "hansa.repeated_size": repeated_chars,
                      "hansa.tool_schema_size": shape.get("tool_schema_chars", 0),
                      "hansa.tool_calls": ",".join(output.get("tool_calls", [])),
                      "hansa.finish_reason": output.get("finish_reason", "")}
        for name, value in (("prompt", row["prompt_tokens"]), ("completion", row["completion_tokens"])):
            if value is not None:
                attributes[f"neatlogs.llm.token_count.{name}"] = value
        spans.append({"span_id": f"{prefix}-{row['id']}", "name": f"chat {row['upstream_model'] or row['model']}", "kind": "LLM",
                      "status_code": "OK" if row["http_status"] == 200 else "ERROR",
                      "start_time": iso(row["started_at_ms"]), "end_time": iso(row["started_at_ms"] + latency),
                      "attributes": attributes, "_start": row["started_at_ms"], "_end": row["started_at_ms"] + latency})
    return spans


def parent_of(spans, start):
    """The model call that most recently finished before this moment asked for whatever happens next."""
    earlier = [span for span in spans if span["kind"] == "LLM" and span["_end"] <= start + 5]
    return earlier[-1]["span_id"] if earlier else None


def gap_spans(model):
    gaps = []
    for before, after in zip(model, model[1:]):
        if after["_start"] - before["_end"] >= GAP_MS:
            gaps.append({"span_id": f"gap-{before['span_id']}", "parent_span_id": before["span_id"],
                         "name": "agent code and tools (inferred gap)", "kind": "CHAIN", "status_code": "UNSET",
                         "start_time": iso(before["_end"]), "end_time": iso(after["_start"]),
                         "attributes": {"hansa.inferred": True, "hansa.gap_ms": after["_start"] - before["_end"]},
                         "_start": before["_end"], "_end": after["_start"]})
    return gaps


def egress_spans(connections, model):
    spans = []
    for index, record in enumerate(connections):
        if type(record.get("started_at")) not in {int, float} or type(record.get("duration_ms")) is not int:
            continue
        start = int(record["started_at"] * 1000)
        target = f"{record.get('method')} {record.get('host')}:{record.get('port')}"
        span = {"span_id": f"egress-{index}", "name": f"http {record.get('host')}", "kind": "TOOL",
                "status_code": "OK" if record.get("allowed") else "ERROR",
                "start_time": iso(start), "end_time": iso(start + record["duration_ms"]),
                "attributes": {"neatlogs.tool.name": "http_egress", "neatlogs.tool.input": target,
                               "neatlogs.tool.output": (f"{record.get('bytes_down')} bytes received" if record.get("allowed")
                                                        else f"refused: {record.get('reason')}"),
                               "hansa.inferred": False, "hansa.allowed": bool(record.get("allowed"))},
                "_start": start, "_end": start + record["duration_ms"]}
        parent = parent_of(model, start)
        if parent:
            span["parent_span_id"] = parent
        spans.append(span)
    return spans


TEXT_ATTRIBUTES = ("neatlogs.input.value", "neatlogs.output.value", "neatlogs.tool.input", "neatlogs.tool.output")
WITHHELD = "content withheld: the trace endpoint refused the full payload"


def without_content(arguments, tools_only=False):
    """Same trace with free text removed; names, sizes, tokens, timings and costs stay.

    tools_only drops only tool inputs and outputs, where code and file paths appear.
    """
    stripped = {**arguments, "metadata": {**arguments["metadata"], "hansa_content": "partial" if tools_only else "withheld"},
                "spans": []}
    if not tools_only:
        stripped.update(input=WITHHELD, output=WITHHELD)
    for span in arguments["spans"]:
        if tools_only and span["kind"] != "TOOL":
            stripped["spans"].append(span)
            continue
        attributes = {key: value for key, value in span["attributes"].items() if key not in TEXT_ATTRIBUTES}
        stripped["spans"].append({**span, "attributes": {**attributes, "hansa.content_withheld": True}})
    return stripped


def parts(arguments):
    """Split a long trace so no request carries more model spans than the endpoint accepts."""
    chunks, current, models = [], [], 0
    for span in arguments["spans"]:
        if span["kind"] == "LLM" and models == MODEL_SPANS_PER_TRACE:
            chunks.append(current)
            current, models = [], 0
        current.append(span)
        models += span["kind"] == "LLM"
    chunks.append(current)
    if len(chunks) == 1:
        return [arguments]
    result = []
    for index, chunk in enumerate(chunks, 1):
        present = {span["span_id"] for span in chunk}
        # A tool whose calling model span fell into the previous part attaches to this part's root instead.
        spans = [{key: value for key, value in span.items() if key != "parent_span_id" or value in present} for span in chunk]
        part = {**arguments, "spans": spans, "metadata": {**arguments["metadata"], "hansa_part": f"{index}/{len(chunks)}"}}
        if index > 1:
            part.pop("cost_usd", None)  # the whole job's cost is stated once, on the first part
        result.append(part)
    return result


def finalize(spans):
    spans = sorted(spans, key=lambda span: span["_start"])[:MAX_SPANS]
    return [{key: value for key, value in span.items() if not key.startswith("_")} for span in spans]


class TraceService:
    def __init__(self, settings, database, inspection, client=None):
        self.settings, self.database, self.inspection = settings, database, inspection
        self.client = client or NeatlogsClient(settings)

    @property
    def enabled(self):
        return self.client.enabled

    def calls(self, key_hash):
        with self.database.connect() as db:
            return db.execute("SELECT * FROM model_calls WHERE key_hash=? ORDER BY started_at_ms, id", (key_hash,)).fetchall()

    def repository(self, import_id):
        with self.database.connect() as db:
            row = db.execute("SELECT repository_name FROM repository_imports WHERE id=?", (import_id,)).fetchone()
        return row["repository_name"] if row else "unknown"

    def send(self, import_id, kind, arguments, summary, run_id=None, job_id=None):
        """Never raises: a tracing failure must not fail or change the run it describes."""
        if not self.enabled:
            return None
        # The ingest endpoint's request filter rejects some ordinary text (a file path such as
        # "../../etc/passwd" in a tool argument is enough). Keep the measurements and drop text in steps.
        trace_ids, levels = [], []

        def deliver(part, depth=0):
            """Send with less text each time; if even the text-free form is refused, halve the part and retry."""
            for content, candidate in (("exported", part), ("partial", without_content(part, tools_only=True)),
                                       ("withheld", without_content(part))):
                try:
                    result = self.client.call("log_trace", candidate)
                except NeatlogsError as exc:
                    if exc.status != 403:
                        raise
                    continue
                if not isinstance(result["trace_id"], str) or not 8 <= len(result["trace_id"]) <= 64:
                    raise NeatlogsError("Neatlogs returned an invalid trace ID.")
                trace_ids.append(result["trace_id"])
                levels.append(content)
                return
            # What the filter objects to was not fully isolated, so shrink until it accepts.
            if len(part["spans"]) < 4 or depth >= 4:
                raise NeatlogsError("Neatlogs log_trace failed with status 403.", 403)
            middle = len(part["spans"]) // 2
            for half in (part["spans"][:middle], part["spans"][middle:]):
                present = {span["span_id"] for span in half}
                deliver({**part, "spans": [{key: value for key, value in span.items()
                                             if key != "parent_span_id" or value in present} for span in half],
                         "metadata": {**part["metadata"], "hansa_split": depth + 1}}, depth + 1)

        try:
            for part in parts(arguments):
                deliver(part)
            trace_id = trace_ids[0]
            content = "withheld" if "withheld" in levels else "partial" if "partial" in levels else "exported"
        except (NeatlogsError, KeyError, TypeError) as exc:
            return {"status": "failed", "reason": str(exc)[:200] if isinstance(exc, NeatlogsError) else "Unexpected Neatlogs result.",
                    "trace_ids": trace_ids}
        with self.database.connect() as db:
            for index, part_id in enumerate(trace_ids, 1):
                described = {**summary, "content": content, **({"part": f"{index}/{len(trace_ids)}"} if len(trace_ids) > 1 else {})}
                db.execute("INSERT OR REPLACE INTO traces (trace_id,import_id,kind,run_id,job_id,summary,created_at) VALUES (?,?,?,?,?,?,?)",
                           (part_id, import_id, kind, run_id, job_id, json.dumps(described), int(time.time())))
        return {"status": "queued", "trace_id": trace_id, "spans": len(arguments["spans"]), "content": content,
                **({"trace_ids": trace_ids} if len(trace_ids) > 1 else {})}

    def log_run(self, import_id, key_hash, result, task, labels=None):
        labels = labels or {}
        kind = str(labels.get("kind") or "run")[:40]
        model = llm_spans(self.calls(key_hash))
        egress = egress_spans((result.get("egress") or {}).get("connections", []), model)
        usage = result["gateway"]
        cost = usage.get("estimated_cost_usd")
        known = cost is not None and not usage.get("unknown_cost_calls")
        summary = {"kind": kind, "stop_reason": result["stop_reason"], "wall_time_seconds": result["wall_time_seconds"],
                   "model_calls": usage["calls"], "tokens_in": usage["prompt_tokens"], "tokens_out": usage["completion_tokens"],
                   "cost_usd": cost if known else None, "external_calls": len(egress),
                   "repeated_chars": sum(span["attributes"]["hansa.repeated_size"] for span in model),
                   "prompt_chars": sum(span["attributes"]["hansa.prompt_size"] for span in model),
                   "task_id": str(labels.get("task_id") or "")[:120]}
        content = self.settings.trace_content
        arguments = {"workflow_name": "hansa-" + kind, "agent_name": self.repository(import_id),
                     "input": redact(task, 2000) if content else "content not exported",
                     "output": redact(result.get("output"), 2000) if content else "content not exported",
                     "latency_ms": int(result["wall_time_seconds"] * 1000),
                     "metadata": {"hansa_import": marker(import_id), "hansa_run": result["run_id"], "hansa_kind": kind,
                                  "hansa_job": str(labels.get("job_id") or ""), "hansa_task": summary["task_id"],
                                  "commit_sha": result.get("commit_sha"), "adapter_sha256": result.get("adapter_sha256"),
                                  "stop_reason": result["stop_reason"], "exit_code": result.get("exit_code"),
                                  "hansa_cost_usd": cost if known else "unknown",
                                  "hansa_cost_source": "LiteLLM response header; not invoice-reconciled",
                                  "internet": (result.get("isolation") or {}).get("internet", "none"),
                                  "coverage": COVERAGE},
                     "spans": finalize(model + gap_spans(model) + egress)}
        if known:
            arguments["cost_usd"] = cost
        # No top-level token_usage: Neatlogs turns it into an extra LLM span, which double-counts the per-call spans.
        return self.send(import_id, kind, arguments, summary, run_id=result["run_id"], job_id=labels.get("job_id"))

    def log_job(self, import_id, job_id, kind, key_hash, steps, status, summary_text, started_ms):
        """One trace for an agent job: its model calls and each tool it used, in order."""
        model = llm_spans(self.calls(key_hash), prefix="agent")
        tools = []
        for index, step in enumerate(steps):
            span = {"span_id": f"tool-{index}", "name": step["name"], "kind": "TOOL",
                    "status_code": "OK" if step["ok"] else "ERROR",
                    "start_time": iso(step["start_ms"]), "end_time": iso(step["end_ms"]),
                    "attributes": {"neatlogs.tool.name": step["name"], "neatlogs.tool.input": redact(step["input"], 1500),
                                   "neatlogs.tool.output": redact(step["output"], 1500), "hansa.inferred": False,
                                   **({"hansa.run_trace_id": step["trace_id"]} if step.get("trace_id") else {})},
                    "_start": step["start_ms"], "_end": step["end_ms"]}
            parent = parent_of(model, step["start_ms"])
            if parent:
                span["parent_span_id"] = parent
            tools.append(span)
        # Neatlogs does not return a step's input and output on readback, so keep a bounded, redacted copy here.
        with self.database.connect() as db:
            db.executemany("INSERT OR REPLACE INTO trace_steps VALUES (?,?,?,?)", [(job_id, import_id, f"tool-{index}", json.dumps({
                "name": step["name"], "ok": bool(step["ok"]), "input": step_input(step),
                "output": step_output(step)})) for index, step in enumerate(steps)])
        cost = sum(row["estimated_cost_usd"] or 0 for row in self.calls(key_hash))
        summary = {"kind": kind, "status": status, "model_calls": len(model), "tool_calls": len(tools), "cost_usd": cost}
        arguments = {"workflow_name": "hansa-" + kind, "agent_name": "hansa-agent",
                     "input": f"{kind} for {self.repository(import_id)}", "output": redact(summary_text, 2000),
                     "latency_ms": max(0, int(time.time() * 1000) - started_ms), "cost_usd": cost,
                     "metadata": {"hansa_import": marker(import_id), "hansa_job": job_id, "hansa_kind": kind,
                                  "status": status, "hansa_cost_usd": cost,
                                  "hansa_cost_source": "LiteLLM response header; not invoice-reconciled"},
                     "spans": finalize(model + tools)}
        return self.send(import_id, kind, arguments, summary, job_id=job_id)

    # -- readback: only traces this application logged for an import its owner can read ---------

    def list(self, user_id, import_id):
        with self.database.connect() as db:
            self.inspection.ready(db, user_id, import_id)
            rows = db.execute("SELECT * FROM traces WHERE import_id=? ORDER BY created_at DESC, rowid DESC LIMIT 200",
                              (import_id,)).fetchall()
        return {"enabled": self.enabled, "traces": [{"trace_id": row["trace_id"], "kind": row["kind"], "run_id": row["run_id"],
                "job_id": row["job_id"], "created_at": row["created_at"], **json.loads(row["summary"]),
                "status": row["status"], "checked_at": row["checked_at"], "confirmed_at": row["confirmed_at"],
                "last_error": row["last_error"]} for row in rows]}

    def owned(self, user_id, import_id, trace_id):
        with self.database.connect() as db:
            self.inspection.ready(db, user_id, import_id)
            row = db.execute("SELECT * FROM traces WHERE trace_id=? AND import_id=?", (trace_id, import_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Trace not found.")
        return dict(row)

    def context(self, user_id, import_id, trace_id):
        checked = self.recheck(user_id, import_id, trace_id)
        if checked.get("error"):
            raise HTTPException(502, checked["error"])
        context = checked["context"]
        row = self.owned(user_id, import_id, trace_id)
        context["hansa"] = {"kind": row["kind"], "summary": json.loads(row["summary"]),
                            "steps": self.ledger(row, context.get("spans") or []),
                            "tools": self.tool_steps(row, context.get("spans") or [])}
        return context

    def tool_steps(self, trace, spans):
        """What each of Hansa's own tool steps took in and gave back, for a job's trace."""
        wanted = [str(span.get("span_id")) for span in spans if str(span.get("span_id") or "").startswith("tool-")]
        if not wanted or not trace["job_id"]:
            return {}
        marks = ",".join("?" * len(wanted))
        with self.database.connect() as db:
            rows = db.execute(f"SELECT span_id, detail FROM trace_steps WHERE job_id=? AND import_id=? AND span_id IN ({marks})",
                              (trace["job_id"], trace["import_id"], *wanted)).fetchall()
        return {row["span_id"]: json.loads(row["detail"]) for row in rows}

    def ledger(self, trace, spans):
        """What Hansa's own gateway recorded for each model call in a trace, keyed by span ID.

        Neatlogs returns a step's name and duration but not the attributes sent with it, so the figures come
        from the ledger. Span IDs are the ones this application wrote when it logged the trace.
        """
        wanted = {}
        for span in spans:
            prefix, _, number = str(span.get("span_id") or "").partition("-")
            if prefix in ("llm", "agent") and number.isdigit():
                wanted[int(number)] = prefix
        if not wanted:
            return {}
        marks = ",".join("?" * len(wanted))
        with self.database.connect() as db:
            keys = db.execute(f"SELECT DISTINCT c.key_hash, k.run_label FROM model_calls c JOIN gateway_keys k "
                              f"ON k.key_hash=c.key_hash WHERE c.id IN ({marks})", tuple(wanted)).fetchall()
        steps = {}
        for key in keys:
            # A run's trace names its run; only that run's key may explain it.
            if trace["run_id"] and key["run_label"] != trace["run_id"]:
                continue
            prefix = next(iter(set(wanted.values())))
            for span in llm_spans(self.calls(key["key_hash"]), prefix=prefix):
                if span["span_id"] in {f"{wanted[number]}-{number}" for number in wanted}:
                    found = span["attributes"]
                    steps[span["span_id"]] = {
                        "model": found["hansa.served_model"], "requested_model": found["hansa.requested_model"],
                        "tokens_in": found.get("neatlogs.llm.token_count.prompt"),
                        "tokens_out": found.get("neatlogs.llm.token_count.completion"),
                        "cost_usd": found["hansa.cost_usd"] if isinstance(found["hansa.cost_usd"], (int, float)) else None,
                        "http_status": found["hansa.http_status"], "messages": found["hansa.messages"],
                        "prompt_chars": found["hansa.prompt_size"], "repeated_messages": found["hansa.repeated_messages"],
                        "repeated_chars": found["hansa.repeated_size"], "tool_schema_chars": found["hansa.tool_schema_size"],
                        "tool_calls": [name for name in found["hansa.tool_calls"].split(",") if name],
                        "finish_reason": found["hansa.finish_reason"]}
        return steps

    def recheck(self, user_id, import_id, trace_id):
        row = self.owned(user_id, import_id, trace_id)
        now, context, error = int(time.time()), None, None
        try:
            # Field projection and clipping are refused as "not_enabled" on this deployment; ask for the default view.
            context = self.client.call("get_trace_context", {"trace_id": trace_id})
            if not isinstance(context, dict) or context.get("trace_id") != trace_id:
                raise NeatlogsError("Neatlogs returned a different or missing trace ID.")
        except NeatlogsError as exc:
            error = str(exc)
            context = None
        confirmed = context is not None and (context.get("verification_ready") is True or
                    context.get("finalization_status") == "finalized")
        status = "confirmed" if confirmed or row["status"] == "confirmed" else "queued"
        note = error or (None if confirmed else "Readback is pending finalization.")
        with self.database.connect() as db:
            self.inspection.ready(db, user_id, import_id)
            db.execute("UPDATE traces SET status=?,checked_at=?,confirmed_at=COALESCE(confirmed_at,?),last_error=? WHERE trace_id=? AND import_id=?",
                       (status, now, now if confirmed else None, note, trace_id, import_id))
        return {"trace_id": trace_id, "status": status, "checked_at": now,
                "confirmed_at": row["confirmed_at"] or (now if confirmed else None),
                "error": error, "note": note, "context": context}

    def search(self, user_id, import_id, query, limit=20):
        """Keyword search in Neatlogs, kept to this import's traces by our own record of what we logged.

        The project is shared by every import, so results are filtered here against the trace IDs
        recorded for this one. A match outside the first 100 project-wide results is not returned.
        """
        known = {item["trace_id"] for item in self.list(user_id, import_id)["traces"]}
        try:
            found = self.client.call("search_traces", {"query": query[:300], "limit": 100})
        except NeatlogsError as exc:
            raise HTTPException(502, str(exc)) from None
        results = [item for item in found.get("results", []) if isinstance(item, dict) and item.get("trace_id") in known]
        return {"results": results[:limit]}

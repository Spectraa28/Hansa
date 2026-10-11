"""What a measured agent is made of, read straight from the call ledger. No model is involved.

Every model call the target made went through the gateway, which kept sizes and per-message hashes
(never the conversation). That is enough to say, as measured fact, how much of each request was
already sent, how much is tool definitions, which calls only hand the conversation on, and where
the time went. Estimates built on those facts are labelled as estimates.
"""
import json

from ..gateway.shape import repeated_prefix

# Providers bill a cached prompt read at roughly a tenth of the normal input price, and output
# tokens at several times the input price. Used only for the labelled estimate.
CACHED_READ_DISCOUNT = 0.9
OUTPUT_PRICE_RATIO = 5


def run_calls(db, run_id):
    return db.execute("""SELECT m.id,m.upstream_model,m.prompt_tokens,m.completion_tokens,m.latency_ms,m.estimated_cost_usd,
        m.started_at_ms,m.request_shape,m.response_shape FROM model_calls m JOIN gateway_keys k ON k.key_hash=m.key_hash
        WHERE k.run_label=? ORDER BY m.started_at_ms,m.id LIMIT 1000""", (run_id,)).fetchall()


def share(part, whole):
    return round(part / whole * 100, 1) if whole else None


def anatomy(database, baseline):
    """Totals over every recorded run of a completed baseline, plus the plain-language readings they support."""
    total = {"calls": 0, "runs": 0, "system": 0, "tools": 0, "conversation": 0, "repeated": 0, "tokens_in": 0, "tokens_out": 0,
             "cost": 0.0, "model_ms": 0, "wall_ms": 0, "handoffs": 0, "handoff_cost": 0.0, "duplicates": 0, "duplicate_cost": 0.0,
             "slowest_ms": 0, "first_calls_chars": 0}
    models, unknown = {}, False
    with database.connect() as db:
        for task in baseline.get("tasks", []):
            for run in task.get("runs", []):
                rows = run_calls(db, run.get("run_id") or "")
                if not rows:
                    continue
                total["runs"] += 1
                total["wall_ms"] += (run.get("wall_time_seconds") or 0) * 1000
                previous, seen = {}, set()
                for row in rows:
                    shape, response = json.loads(row["request_shape"] or "{}"), json.loads(row["response_shape"] or "{}")
                    roles = shape.get("chars_by_role") or {}
                    system, tools = roles.get("system", 0), shape.get("tool_schema_chars") or 0
                    conversation = (shape.get("prompt_chars") or 0) - system
                    _, repeated = repeated_prefix(previous, shape)
                    # Tool definitions of the same size as the call before are counted as sent again.
                    repeated += tools if previous and tools and tools == (previous.get("tool_schema_chars") or 0) else 0
                    cost = row["estimated_cost_usd"]
                    unknown = unknown or cost is None or row["prompt_tokens"] is None
                    total["calls"] += 1
                    total["system"] += system
                    total["tools"] += tools
                    total["conversation"] += conversation
                    total["repeated"] += repeated
                    total["tokens_in"] += row["prompt_tokens"] or 0
                    total["tokens_out"] += row["completion_tokens"] or 0
                    total["cost"] += cost or 0
                    total["model_ms"] += row["latency_ms"] or 0
                    total["slowest_ms"] = max(total["slowest_ms"], row["latency_ms"] or 0)
                    if not response.get("output_chars") and len(response.get("tool_calls") or []) == 1:
                        total["handoffs"] += 1
                        total["handoff_cost"] += cost or 0
                    fingerprint = (tuple(shape.get("message_hashes") or ()), tools)
                    if shape.get("message_hashes") and fingerprint in seen:
                        total["duplicates"] += 1
                        total["duplicate_cost"] += cost or 0
                    seen.add(fingerprint)
                    models[row["upstream_model"] or "unknown"] = models.get(row["upstream_model"] or "unknown", 0) + 1
                    previous = shape
    if not total["calls"]:
        return None
    sent = total["system"] + total["tools"] + total["conversation"]
    runs, calls = total["runs"], total["calls"]
    weighted = total["tokens_in"] + OUTPUT_PRICE_RATIO * total["tokens_out"]
    input_cost = total["cost"] * total["tokens_in"] / weighted if weighted else 0
    cache_saving = input_cost * (total["repeated"] / sent if sent else 0) * CACHED_READ_DISCOUNT
    gap_ms = max(0, total["wall_ms"] - total["model_ms"])
    result = {
        "runs": runs, "model_calls": calls, "calls_per_run": round(calls / runs, 1), "models": models,
        "input": {"chars": sent, "system_percent": share(total["system"], sent), "tool_schema_percent": share(total["tools"], sent),
                  "conversation_percent": share(total["conversation"], sent), "sent_before_percent": share(total["repeated"], sent)},
        "time": {"model_percent": share(total["model_ms"], total["wall_ms"]), "outside_model_percent": share(gap_ms, total["wall_ms"]),
                 "seconds_per_call": round(total["model_ms"] / calls / 1000, 2), "slowest_call_seconds": round(total["slowest_ms"] / 1000, 2)},
        "handoff_calls": {"count": total["handoffs"], "percent": share(total["handoffs"], calls),
                          "cost_usd": None if unknown else round(total["handoff_cost"], 6)},
        "duplicate_calls": {"count": total["duplicates"], "cost_usd": None if unknown else round(total["duplicate_cost"], 6)},
        "cost_usd": None if unknown else round(total["cost"], 6),
        # How much of the bill is input, under the stated price ratio. Estimates of input savings scale by this.
        "input_cost_percent": share(input_cost, total["cost"]),
        "prompt_caching_estimate": None if unknown else {
            "saving_usd": round(cache_saving, 6), "saving_percent": share(cache_saving, total["cost"]),
            "assumes": "A cached read costs a tenth of normal input and output tokens cost five times input. "
                       "Providers also set a minimum cacheable size and charge more to write a cache entry."},
        "note": "Measured from request sizes and hashes over every recorded baseline run. Sizes are characters, not tokens.",
    }
    result["readings"] = readings(result)
    return result


def readings(x):
    """One sentence per area where the numbers say something. Thresholds are deliberately plain."""
    out, i, t = [], x["input"], x["time"]

    def add(area, headline, detail, strength):
        out.append({"area": area, "headline": headline, "detail": detail, "strength": strength})
    if (i["sent_before_percent"] or 0) >= 40:
        saving = x["prompt_caching_estimate"]
        add("Context", f"{i['sent_before_percent']:.0f}% of what the agent sends, it already sent on the call before.",
            "The same opening messages go out again on every step. Prompt caching bills repeated input at a fraction of the price"
            + (f"; a rough estimate is {saving['saving_percent']:.0f}% off the bill." if saving and saving["saving_percent"] else "."),
            "strong" if i["sent_before_percent"] >= 60 else "medium")
    if (i["tool_schema_percent"] or 0) >= 20:
        add("Tools", f"Tool definitions are {i['tool_schema_percent']:.0f}% of every request.",
            "Each call ships the full description of every tool. Shorter descriptions, or only the tools a step can use, cut this directly.",
            "strong" if i["tool_schema_percent"] >= 35 else "medium")
    if (i["system_percent"] or 0) >= 30:
        add("Context", f"The system prompt is {i['system_percent']:.0f}% of what is sent.",
            "A long fixed prompt is paid for on every call. It is the first thing worth trimming or caching.", "medium")
    h = x["handoff_calls"]
    if h["count"] and (h["percent"] or 0) >= 20:
        add("Orchestration", f"{h['count']} of {x['model_calls']} model calls say nothing and make a single tool call.",
            "Where that tool only hands the conversation to another agent, the whole call is routing overhead: a full model call spent on a decision "
            "that may not need a model.", "strong" if h["percent"] >= 35 else "medium")
    d = x["duplicate_calls"]
    if d["count"]:
        add("Wasted work", f"{d['count']} call{'s' if d['count'] != 1 else ''} sent exactly the same request as an earlier call in the same run.",
            "An identical request gets a fresh, separately billed answer. Reusing the first answer removes the call.", "strong")
    if (t["outside_model_percent"] or 0) >= 35:
        add("Latency", f"{t['outside_model_percent']:.0f}% of the run time is spent outside the model.",
            "That is the agent's own code, its tools and waiting between calls. Speeding up the model will not touch it.", "medium")
    if x["calls_per_run"] >= 8:
        add("Orchestration", f"Each task takes {x['calls_per_run']:g} model calls on average.",
            "Every extra step resends the conversation so far, so cost grows faster than the number of steps.", "medium")
    return out

"""What an experienced agent engineer would change, chosen from measurements. No model is called.

Each play is a known way to cut an agent's cost or latency. A play applies when the baseline X-ray or a
static read of the source says it should, carries the evidence that triggered it, and estimates its
effect with the arithmetic shown. Plays are sorted into two kinds, because the difference matters:

  safe         changes how requests are sent, not what the agent does or says
  needs_proof  changes behaviour, so it must be re-measured on the task set before it is trusted

The owner picks plays; `brief` turns the selection into one implementation brief for a coding agent.
The source is read as text only: paths and line numbers leave this module, never source excerpts.
"""
import os
import re
from pathlib import Path

MAX_FILES, MAX_BYTES, MAX_HITS = 600, 262144, 4
SKIP = {"node_modules", "__pycache__", ".venv", "venv", "dist", "build", "tests", "test", "docs", ".git", "site-packages"}
PATTERNS = {
    "model_call": r"chat\.completions\.create|messages\.create\(|litellm\.a?completion|responses\.create\(|Chat(OpenAI|Anthropic|Groq|LiteLLM)\(|init_chat_model\(",
    "cache_marker": r"cache_control|prompt_cache_key|cached_content",
    "output_cap": r"max_tokens|max_completion_tokens|max_output_tokens",
    "unbounded_loop": r"max_(turns|iterations|steps)\b[^=\n]*=\s*(float\(\s*['\"]inf|None\b)|while\s+True\s*:",
    "changing_value": r"datetime\.(now|utcnow)\(|date\.today\(|time\.time\(|uuid\.uuid\d\(|random\.",
    "prompt_definition": r"(instructions|system_prompt|SYSTEM_PROMPT|system_message|STARTER_PROMPT)\s*=|['\"]role['\"]\s*:\s*['\"]system['\"]",
    "parallel": r"asyncio\.gather|ThreadPoolExecutor|parallel_tool_calls\s*=\s*True",
    "tool_definition": r"\bfunctions\s*=\s*\[|\btools\s*=\s*\[|@tool\b|['\"]type['\"]\s*:\s*['\"]function['\"]",
}


# The shape of each change, for a reader who will write the real one. Illustrations, not drop-in code.
EXAMPLES = {
    "prompt-caching": '''# OpenAI-style chat call to a Claude model (directly or through LiteLLM): mark the end of the fixed prefix.
messages = [
    {"role": "system", "content": [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
    ]},
    *history,
]
# Anthropic SDK: system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
# Then log the cached-token count the provider returns in `usage` on each response.''',
    "stable-prefix": '''# Before: the prefix changes every call, so nothing can be cached.
system = f"Today is {date.today()}. You are a support agent. ..."
# After: fixed text first, built once; what changes goes last.
SYSTEM = "You are a support agent. ..."                       # module level, never re-rendered
messages = [{"role": "system", "content": SYSTEM}, *history,
            {"role": "user", "content": f"(Today is {date.today()}.) {user_message}"}]''',
    "bound-turns": '''MAX_TURNS = 20   # about three times the longest task in the baseline
for turn in range(MAX_TURNS):
    ...
else:
    log.warning("turn ceiling reached")          # a bug to look at
    return {"status": "could_not_complete"}''',
    "cap-output": '''client.chat.completions.create(model=MODEL, messages=messages, max_tokens=800)   # answers
client.chat.completions.create(model=MODEL, messages=messages, max_tokens=120)   # steps that only pick a tool''',
    "reuse-answers": '''answers = {}                                    # one per task, never shared across users
key = json.dumps(messages, sort_keys=True)
if key not in answers:
    answers[key] = client.chat.completions.create(model=MODEL, messages=messages)
reply = answers[key]''',
}


def closeness(path, entry):
    """0 for the agent's own folder, 2 for a neighbouring app in the same parent folder, 1 for everything else."""
    if not entry:
        return 1
    parts, home = Path(path).parts, Path(entry).parts
    if parts[:len(home)] == home:
        return 0
    return 2 if home and parts[:len(home) - 1] == home[:-1] and len(parts) > len(home) else 1


def scan(root, entrypoint=None):
    """Where in the source each kind of thing appears. Bounded; returns paths and line numbers only.

    A repository often holds several apps. Hits are ranked so the lines shown are in the agent that was
    measured (the folder of its entrypoint) or in shared library code, before any neighbouring example.
    """
    root, found, files = Path(root), {key: [] for key in PATTERNS}, 0
    script = next((token for token in (entrypoint or "").split() if token.endswith(".py")), None)
    entry = str(Path(script).parent) if script and "/" in script else None
    compiled = {key: re.compile(pattern) for key, pattern in PATTERNS.items()}
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in SKIP and not name.startswith("."))
        for name in sorted(names):
            path = Path(folder) / name
            if path.suffix != ".py" or path.is_symlink() or files >= MAX_FILES:
                continue
            try:
                if path.stat().st_size > MAX_BYTES:
                    continue
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            files += 1
            prompt_file = any(compiled["prompt_definition"].search(line) for line in lines)
            for number, line in enumerate(lines, 1):
                for key, pattern in compiled.items():
                    # A clock or random value only matters where a prompt is being built.
                    if key == "changing_value" and not prompt_file:
                        continue
                    if len(found[key]) < 300 and pattern.search(line):
                        found[key].append({"path": str(path.relative_to(root)), "line": number})
    for key, hits in found.items():
        # A neighbouring app's code says nothing about the agent that was measured.
        hits = [hit for hit in hits if closeness(hit["path"], entry) < 2]
        hits.sort(key=lambda hit: (closeness(hit["path"], entry), hit["path"].count("/"), hit["path"], hit["line"]))
        found[key] = hits[:MAX_HITS]
    return {"files_read": files, **found}


def where(hits):
    return [f"{hit['path']}:{hit['line']}" for hit in hits]


def plays(xray, source):
    """Every play that applies, most valuable first. `xray` may be None when no baseline exists yet."""
    out = []
    i, t = (xray or {}).get("input") or {}, (xray or {}).get("time") or {}
    input_share = ((xray or {}).get("input_cost_percent") or 0) / 100
    calls = (xray or {}).get("model_calls") or 0

    def add(play_id, area, kind, title, why, evidence, steps, keep, check, cost=None, latency=None, basis=None, at=()):
        out.append({"id": play_id, "area": area, "kind": kind, "title": title, "why": why, "evidence": [e for e in evidence if e],
                    "steps": steps, "keep": keep, "check": check, "where": where(at), "example": EXAMPLES.get(play_id),
                    "estimate": {"cost_percent": round(cost, 1) if cost else None, "latency_percent": round(latency, 1) if latency else None,
                                 "basis": basis}})

    repeat = i.get("sent_before_percent") or 0
    if xray and repeat >= 30 and not source["cache_marker"]:
        saving = (xray.get("prompt_caching_estimate") or {}).get("saving_percent")
        add("prompt-caching", "Context", "safe", "Turn on prompt caching",
            "The agent resends the same opening on every call and pays full price for it each time. A cached prefix is billed at about a tenth.",
            [f"{repeat:.0f}% of each request was already sent on the call before (measured over {calls} calls).",
             "No cache markers were found in the source."],
            ["Find every place a model request is built (see the listed lines).",
             "Mark the end of the unchanging prefix as cacheable: for Anthropic models add `cache_control: {\"type\": \"ephemeral\"}` to the last system block and to the last tool definition; "
             "OpenAI models cache automatically once the unchanging prefix is long enough, so only the ordering work below is needed there.",
             "Keep the cache alive between calls of one conversation: do not rebuild or reorder the prefix between turns.",
             "Log the provider's cached-token count from each response so the hit rate can be seen."],
            "Do not change any prompt wording, tool, or model. This changes how the request is billed, not what is sent.",
            "Run the same tasks twice in a row: cached input tokens should be above zero on every call after the first, and answers unchanged.",
            cost=saving, basis="repeat share × input share of the bill × 90% cached-read discount", at=source["model_call"])
    if xray and (i.get("system_percent") or 0) >= 25 and (source["changing_value"] or repeat < 40):
        add("stable-prefix", "Context", "safe", "Put what never changes first, what changes last",
            "A cache only covers an identical prefix. One timestamp, ID or user detail near the top of the prompt makes every call a miss.",
            [f"The system prompt is {i['system_percent']:.0f}% of every request.",
             "Values that change per call are built in files that define prompts." if source["changing_value"] else
             f"Only {repeat:.0f}% of each request repeats the call before, which is low for a prompt this size."],
            ["Order each request as: fixed instructions, then tool definitions, then fixed examples, then the conversation, then anything that changes per call.",
             "Move dates, times, request IDs, user names and retrieved data out of the system prompt into the final user message.",
             "Build the fixed part once at start-up and reuse the same string; do not re-render it with a template on each call.",
             "Keep tool definitions in a stable order (sort them) so the same list is byte-identical between calls."],
            "Every instruction must still reach the model; only its position changes. Do not reword anything.",
            "Diff the first request of two different tasks: everything before the conversation should be identical.",
            cost=(i["system_percent"] / 100) * input_share * 90 * 0.5 if input_share else None,
            basis="system-prompt share × input share × 90% cached-read discount, halved because some of it may already be cacheable",
            at=source["changing_value"] or source["prompt_definition"])
    if xray and (i.get("tool_schema_percent") or 0) >= 18:
        add("tool-schemas", "Tools", "needs_proof", "Send each step only the tools it can use, with shorter descriptions",
            "Every call carries the full definition of every tool. Most steps can only use one or two of them.",
            [f"Tool definitions are {i['tool_schema_percent']:.0f}% of every request."],
            ["List the tools each agent or step actually calls in the baseline runs.",
             "Pass each step only that subset instead of the whole list.",
             "Cut each tool description to one sentence saying when to use it; move long usage notes into the system prompt once.",
             "Remove parameters and enum values nothing uses."],
            "Do not rename a tool or change what it does or returns. Names and behaviour stay exactly as they are.",
            "Rerun the task set: the same tools must be called in the same tasks.",
            cost=(i["tool_schema_percent"] / 100) * input_share * 100 * 0.5 if input_share else None,
            basis="tool-definition share × input share, assuming definitions can be halved", at=source["tool_definition"])
    handoff = (xray or {}).get("handoff_calls") or {}
    if xray and handoff.get("count") and (handoff.get("percent") or 0) >= 10:
        cost_share = (handoff.get("cost_usd") or 0) / xray["cost_usd"] * 100 if xray.get("cost_usd") else None
        add("route-cheaply", "Model choice", "needs_proof", "Use a small model for calls that only route",
            "A call that says nothing and picks one tool is a classification. A small model does it for a fraction of the price and time.",
            [f"{handoff['count']} of {calls} calls returned a single tool call and no text.",
             f"Those calls are {cost_share:.0f}% of the bill." if cost_share else None],
            ["Identify the agents or steps whose only job is to choose the next agent or tool.",
             "Give those steps a smaller, faster model; leave the steps that write answers on the current model.",
             "Where the choice is a fixed rule (a keyword or a field value), replace the model call with code."],
            "The same next step must be chosen for the same input. Do not change the routing rules themselves.",
            "Rerun the task set and compare which tools were called per task; any difference means the small model is not good enough for that step.",
            cost=cost_share * 0.8 if cost_share else None, latency=(handoff.get("percent") or 0) * 0.5,
            basis="cost of routing-only calls × 80%, assuming a model about five times cheaper", at=source["model_call"])
    if source["unbounded_loop"]:
        add("bound-turns", "Orchestration", "safe", "Put a ceiling on turns",
            "With no limit, one confused conversation can loop until the bill is noticed. A ceiling costs nothing on the normal path.",
            ["A loop or turn limit with no upper bound is set in the source.",
             f"Tasks in the baseline needed {xray['calls_per_run']:g} calls on average." if xray else None],
            ["Set the maximum turns to about three times what the longest baseline task needed.",
             "When the ceiling is hit, stop and return a clear 'could not complete' result instead of raising.",
             "Log every time it is hit; that is a bug to look at, not noise."],
            "Normal tasks must finish exactly as before; the ceiling must sit well above what they use.",
            "Rerun the task set: no task should reach the ceiling.", basis="no saving on the normal path; removes the unbounded worst case",
            at=source["unbounded_loop"])
    if xray and (t.get("outside_model_percent") or 0) >= 30 and not source["parallel"]:
        add("parallel-tools", "Latency", "needs_proof", "Run independent tool calls at the same time",
            "Time outside the model is the agent's own code and its tools. Calls that do not depend on each other can overlap.",
            [f"{t['outside_model_percent']:.0f}% of run time is spent outside the model.", "No parallel execution was found in the source."],
            ["Find steps where the model asks for several tools at once, or where code makes several lookups in a row.",
             "Run those together (asyncio.gather or a small thread pool) and return results in the original order.",
             "Allow the model to request several tools in one turn if the provider supports it."],
            "Only overlap calls that neither read each other's results nor write to the same place.",
            "Rerun the task set: same answers, lower wall time.", latency=t["outside_model_percent"] * 0.4,
            basis="time outside the model × 40%, assuming under half of it can overlap", at=source["model_call"])
    if xray and xray.get("calls_per_run", 0) >= 6 and (i.get("conversation_percent") or 0) >= 25:
        add("trim-history", "Memory", "needs_proof", "Stop carrying the whole conversation into every call",
            "Each step resends everything said so far, so the cost of a task grows with the square of its length.",
            [f"Tasks take {xray['calls_per_run']:g} model calls on average.", f"The conversation is {i['conversation_percent']:.0f}% of what is sent."],
            ["Keep the last few turns whole and replace older tool results with a one-line summary of what they returned.",
             "When control passes to another agent, pass a short brief of what is known instead of the full transcript.",
             "Never drop the user's original request or anything the agent has promised."],
            "Facts the agent needs later must survive the trimming.",
            "Rerun the task set, paying attention to the longest tasks: answers must not lose detail.",
            cost=(i["conversation_percent"] / 100) * input_share * 100 * 0.3 if input_share else None,
            basis="conversation share × input share, assuming 30% of history can be dropped")
    duplicates = ((xray or {}).get("duplicate_calls") or {}).get("count") or 0
    if duplicates:
        add("reuse-answers", "Wasted work", "safe", "Do not ask the same question twice",
            "An identical request gets a new, separately billed answer.", [f"{duplicates} calls repeated an earlier request in the same run exactly."],
            ["Find where the same request is built twice in one task.", "Keep the first answer in a per-task dictionary keyed by the request and reuse it."],
            "Only reuse within one task, never across users or tasks.", "Rerun the task set: the duplicate calls disappear and answers are unchanged.",
            cost=((xray["duplicate_calls"].get("cost_usd") or 0) / xray["cost_usd"] * 100) if xray.get("cost_usd") else None,
            basis="measured cost of the duplicate calls", at=source["model_call"])
    if source["model_call"] and not source["output_cap"]:
        add("cap-output", "Output", "safe", "Set a limit on answer length",
            "Output tokens cost several times more than input and are the slowest part of a call. Without a limit, one rambling answer sets the worst case.",
            ["No output limit was found where model calls are made."],
            ["Set a maximum output length on every model call, sized to about twice the longest answer the baseline produced.",
             "Use a much smaller limit on steps that only pick a tool."],
            "Normal answers must not be cut off.", "Rerun the task set: no answer should end with a length stop.",
            basis="bounds the worst case; little change on normal runs", at=source["model_call"])
    order = {"safe": 0, "needs_proof": 1}
    return sorted(out, key=lambda play: (order[play["kind"]], -(play["estimate"]["cost_percent"] or 0), -(play["estimate"]["latency_percent"] or 0)))


def combined(chosen, key="cost_percent"):
    """Savings overlap, so they compound rather than add: 30% then 20% of the rest is 44%, not 50%."""
    left = 1.0
    for play in chosen:
        left *= 1 - (play["estimate"][key] or 0) / 100
    return round((1 - left) * 100, 1)


def brief(repository, commit, folder, xray, chosen):
    """One work order for the owner's coding agent, written the way a senior engineer hands off work.

    The reader has the repository open and nothing else. So it gets: the job, a task list to tick off, how to
    find the code if lines have moved, each change with evidence, steps, an example and a check, and the
    exact report to send back.
    """
    safe = [play for play in chosen if play["kind"] == "safe"]
    risky = [play for play in chosen if play["kind"] == "needs_proof"]
    ordered = safe + risky
    lines = [f"# Task: make the AI agent in {repository} cheaper and faster", "",
             "You are a senior engineer working in a checkout of this repository" + (f", on the agent in the folder `{folder}`" if folder else "") +
             f". The changes below were chosen from measurements of this agent running its own tasks at commit `{commit[:12]}`, not from guesses. "
             "Carry them out in order.", "",
             "## Task list", ""]
    lines += [f"- [ ] {index}. {play['title']}" + (" (does not change behaviour)" if play["kind"] == "safe" else " (changes behaviour: verify after)")
              for index, play in enumerate(ordered, 1)]
    lines += ["- [ ] Run the tests and send the report at the end", "",
              "## Before you start", "",
              "1. Find how this project runs its tests (README, `pyproject.toml`, `Makefile`, CI config) and run them once so you know the starting state.",
              "2. Open the files listed under each change. Line numbers are from the commit above; if the code has moved, find the same code by function or symbol name.",
              "3. Find where the agent builds its model requests and where it defines its prompts and tools. Most changes below are made there.", "",
              "## Ground rules", "",
              "- Change how the agent is run, not what it does. Tool names, tool behaviour, prompt wording and the shape of the output stay the same unless a change below says otherwise.",
              "- One change per commit, in the order given, so each can be measured and reverted on its own.",
              "- Do not refactor, rename or reformat anything outside the lines you need to touch. No new dependencies.",
              "- If a change cannot be made without altering behaviour, or the code does not match what is described, stop and say so instead of improvising.", ""]
    if xray:
        i = xray["input"]
        lines += ["## What was measured", "", f"Over {xray['model_calls']} model calls in {xray['runs']} task runs:", "",
                  f"- {i['sent_before_percent']:.0f}% of each request had already been sent on the call before.",
                  f"- Each request is {i['system_percent']:.0f}% system prompt, {i['tool_schema_percent']:.0f}% tool definitions and {i['conversation_percent']:.0f}% conversation.",
                  f"- A task takes {xray['calls_per_run']:g} model calls on average; {xray['time']['outside_model_percent']:.0f}% of run time is spent outside the model.", ""]
    number = 0
    for title, group, note in (("Changes that do not alter behaviour", safe, "These change how requests are sent and billed. Do them first."),
                               ("Changes that alter behaviour", risky, "Each of these can change what the agent does. Do one at a time, and after each, run the tests and compare the agent's answers on a few real inputs before going on.")):
        if not group:
            continue
        lines += [f"## {title}", "", note, ""]
        for play in group:
            number += 1
            estimate = play["estimate"]
            effect = ", ".join(part for part in (f"about {estimate['cost_percent']:g}% lower cost" if estimate["cost_percent"] else "",
                                                  f"about {estimate['latency_percent']:g}% less time" if estimate["latency_percent"] else "") if part)
            lines += [f"### {number}. {play['title']}", "", play["why"], ""]
            lines += ["**Evidence**", ""] + [f"- {item}" for item in play["evidence"]]
            if play["where"]:
                lines += ["", "**Start at:** " + ", ".join(f"`{place}`" for place in play["where"])]
            lines += ["", "**Do this**", ""] + [f"{index}. {step}" for index, step in enumerate(play["steps"], 1)]
            if play.get("example"):
                lines += ["", "**The shape of it** (an illustration; adapt it to this codebase's client and names)", "", "```python", play["example"], "```"]
            lines += ["", f"**Must stay true:** {play['keep']}", "", f"**Done when:** {play['check']}", ""]
            if effect:
                lines += [f"**Expected effect (estimate):** {effect}. Basis: {estimate['basis']}.", ""]
    total_cost, total_time = combined(chosen), combined(chosen, "latency_percent")
    lines += ["## Report back", "",
              "When every item on the task list is ticked or explained, reply with:", "",
              "- Each change: done or skipped, the commit, the files and lines touched. For a skipped change, the reason.",
              "- Test results before and after.",
              "- For one task run before and after: total input tokens, cached input tokens, output tokens and time.",
              "- Anything in the code that did not match what this brief describes.", ""]
    if total_cost or total_time:
        lines += ["Estimated combined effect if every change lands: " + " and ".join(part for part in (
            f"about {total_cost:g}% lower cost" if total_cost else "", f"about {total_time:g}% less run time" if total_time else "") if part) +
            ". These are estimates from the measurements above. The real figure comes from running the same tasks again.", ""]
    return "\n".join(lines)

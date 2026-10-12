"""What a change the sandbox cannot measure would save, worked out from the measured baseline and list prices.

The sandbox sends every call to one model, does not bill cached input differently, and runs tasks as written. A model
swap, prompt caching or a guard therefore shows nothing when rerun. These figures are arithmetic over what was
measured; they are never presented as a test result.
"""
import json
from pathlib import Path

PRICES = json.loads(Path(__file__).with_name("model_prices.json").read_text())
# The kinds of change a finding can be. The last three cannot be shown by rerunning the tasks here.
LEVERS = ("remove_call", "fewer_tokens", "less_output", "model_swap", "caching", "guard", "other")
UNTESTABLE = {"model_swap": "The sandbox sends every call to the one model chosen in Setup, so a different model changes nothing it can measure.",
              "caching": "The sandbox does not bill cached input differently, so caching and prompt order change nothing it can measure.",
              "guard": "A guard only acts on a run that goes wrong. On the tasks as written it changes nothing."}


def testable(lever):
    return lever not in UNTESTABLE


def price(model):
    """List price for a model name, or None. Gateway names are mapped first; then any provider's entry."""
    name = str(model or "").strip()
    name = PRICES["gateway_names"].get(name, name).split("/")[-1]
    for provider in PRICES["providers"].values():
        if name in provider["models"]:
            return {**provider["models"][name], "name": name, "verified": provider.get("verified", False)}
    return None


def cheaper_sibling(model):
    """A sensible default target for a swap when the finding does not name one."""
    return {"claude-sonnet-4.6": "claude-haiku", "claude-opus-4.6": "claude-sonnet-4.6"}.get(str(model))


def estimate(finding, baseline, xray):
    """An estimate for an untestable finding, or None when the finding can simply be tested."""
    lever = finding.get("lever") or "other"
    if testable(lever):
        return None
    per_pass = baseline.get("per_pass") or {}
    before = per_pass.get("cost_usd")
    result = {"lever": lever, "why_not_tested": UNTESTABLE[lever], "cost_before_usd": before, "cost_after_usd": None,
              "change_percent": None, "basis": [], "unknowns": [], "prices_retrieved": PRICES["retrieved"]}
    if lever == "guard":
        result.update(cost_after_usd=before, change_percent=0.0)
        result["basis"].append("No saving on a normal run. It limits the damage of a run that loops or rambles.")
        return result
    if before is None:
        result["unknowns"].append("The baseline's cost is not fully known, so no figure can be given.")
        return result
    if lever == "caching":
        cached = (xray or {}).get("prompt_caching_estimate") or {}
        percent = cached.get("saving_percent")
        if percent is None:
            result["unknowns"].append("The baseline has no measure of how much each request repeats.")
            return result
        result.update(cost_after_usd=before * (1 - percent / 100), change_percent=-round(percent, 1))
        repeated = ((xray or {}).get("input") or {}).get("sent_before_percent")
        result["basis"].append(f"{round(repeated or 0)}% of each request repeated the call before it (measured).")
        if cached.get("assumes"):
            result["basis"].append(cached["assumes"])
        result["unknowns"] += ["Providers set a minimum size for a cached prefix; short prompts may not qualify.",
                               "Writing a cache entry costs more than a normal read; this pays back only when the prefix is reused."]
        return result
    # model_swap
    source = baseline.get("litellm_model") or baseline.get("model")
    target = finding.get("swap_to_model") or cheaper_sibling(source)
    old, new = price(source), price(target)
    share = finding.get("calls_affected_percent")
    if not old or not new:
        result["unknowns"].append(f"No list price on record for {source if not old else target}, so the swap cannot be priced.")
        return result
    if share is None:
        result["unknowns"].append("The finding does not say what share of the calls would move to the other model.")
        return result
    tokens_in, tokens_out = per_pass.get("tokens_in") or 0, per_pass.get("tokens_out") or 0
    if not tokens_in + tokens_out:
        result["unknowns"].append("The baseline's token counts are not known.")
        return result
    was = tokens_in * old["input"] + tokens_out * old["output"]
    now = tokens_in * new["input"] + tokens_out * new["output"]
    saving = share / 100 * (1 - now / was)
    result.update(cost_after_usd=before * (1 - saving), change_percent=-round(saving * 100, 1), from_model=source, to_model=target)
    result["basis"] += [f"{round(share)}% of the model calls would move from {source} to {target} (the finding's count of affected calls).",
                        f"List prices per million tokens: {old['name']} ${old['input']:g} in / ${old['output']:g} out; "
                        f"{new['name']} ${new['input']:g} in / ${new['output']:g} out.",
                        f"Applied to this baseline's mix of {round(tokens_in):,} input and {round(tokens_out):,} output tokens per pass, "
                        "treating the affected calls as average-sized."]
    result["unknowns"] += ["Whether the other model still makes the same decisions. Check that on your own tasks before relying on it.",
                           "Speed: a different model's response time was not measured for this agent.",
                           "Your provider or gateway may charge differently from list price."]
    if not (old["verified"] and new["verified"]):
        result["unknowns"].append("One of these list prices comes from a third-party listing, not the provider's own page.")
    return result

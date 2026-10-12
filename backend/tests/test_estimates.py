from app.agent import suggest
from app.agent import estimates
from app.agent.estimates import estimate, price

BASELINE = {"litellm_model": "claude-sonnet-4.6", "per_pass": {"cost_usd": 0.04, "tokens_in": 9000, "tokens_out": 600}}


def test_levers_the_sandbox_cannot_show_are_marked():
    assert all(estimates.testable(lever) for lever in ("remove_call", "fewer_tokens", "other"))
    assert not any(estimates.testable(lever) for lever in ("model_swap", "caching", "guard"))
    assert estimate({"lever": "remove_call"}, BASELINE, None) is None


def test_model_swap_is_priced_from_the_baseline_mix_and_list_prices():
    result = estimate({"lever": "model_swap", "swap_to_model": "claude-haiku", "calls_affected_percent": 66}, BASELINE, None)
    # Haiku 4.5 is a third of Sonnet 4.6 on input and output, so two thirds of 66% of the cost goes.
    assert result["change_percent"] == -44.0
    assert abs(result["cost_after_usd"] - 0.04 * 0.56) < 1e-9
    assert result["from_model"] == "claude-sonnet-4.6" and any("same decisions" in note for note in result["unknowns"])


def test_swap_without_a_known_price_or_share_gives_no_figure():
    assert estimate({"lever": "model_swap", "swap_to_model": "made-up-model", "calls_affected_percent": 50}, BASELINE, None)["change_percent"] is None
    assert estimate({"lever": "model_swap", "swap_to_model": "claude-haiku"}, BASELINE, None)["change_percent"] is None
    assert price("made-up-model") is None and price("gpt-4o")["input"] == 2.5


def test_caching_uses_the_measured_repeat_share_and_a_guard_saves_nothing():
    xray = {"input": {"sent_before_percent": 59}, "prompt_caching_estimate": {"saving_percent": 42.0, "assumes": "A cached read costs a tenth."}}
    cached = estimate({"lever": "caching"}, BASELINE, xray)
    assert cached["change_percent"] == -42.0 and abs(cached["cost_after_usd"] - 0.0232) < 1e-9
    assert estimate({"lever": "guard"}, BASELINE, xray)["change_percent"] == 0.0


def test_pinned_keeps_decisions_and_leaves_wording_and_numbers_alone():
    output = {"answer": "Your refund is on its way.", "agent": "Flight Cancel", "refunded": True, "tools": ["initiate_refund"],
              "elapsed": 3.2, "messages": [{"role": "user", "content": "hi"}], "resolution": {"action": "refund", "note": "x" * 90}}
    rules = {rule["pointer"]: rule["exact_value"] for rule in suggest.pinned(output)}
    assert rules == {"/agent": "Flight Cancel", "/refunded": True, "/tools": ["initiate_refund"], "/resolution/action": "refund"}

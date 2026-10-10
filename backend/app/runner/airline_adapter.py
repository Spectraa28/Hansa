"""Trusted stdin/stdout adapter; imported Swarm code runs only inside Docker."""
import json
from pathlib import Path
import sys


def main():
    task = json.load(sys.stdin)
    if task.get("agent") not in {"triage_agent", "flight_modification"}:
        raise ValueError("Unsupported airline eval agent.")
    # The upstream example uses top-level configs/data imports from its own directory.
    sys.path.insert(0, str(Path("/snapshot/examples/airline")))
    from configs import agents
    from openai import OpenAI
    from swarm import Swarm

    agent = getattr(agents, task["agent"])
    permitted = {"triage_agent": {"transfer_to_flight_modification", "transfer_to_lost_baggage"},
                 "flight_modification": {"transfer_to_flight_cancel", "transfer_to_flight_change"}}
    if {function.__name__ for function in agent.functions} != permitted[task["agent"]]:
        raise ValueError("Airline routing functions differ from the reviewed adapter contract.")
    with OpenAI(max_retries=0, timeout=60) as client:
        response = Swarm(client=client).run(
            agent=agent, messages=task["conversation"],
            max_turns=1, stream=False,
        )
    print(json.dumps({"messages": response.messages, "agent": response.agent.name}))


if __name__ == "__main__":
    main()

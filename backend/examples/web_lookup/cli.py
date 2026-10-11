"""Interactive terminal chat."""
from lookup.agent import LookupAgent


def main():
    agent = LookupAgent()
    print("Ask a question (blank line to quit).")
    while True:
        question = input("> ").strip()
        if not question:
            break
        result = agent.ask(question)
        print(result["answer"])


if __name__ == "__main__":
    main()

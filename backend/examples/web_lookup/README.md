# Web lookup agent (onboarding fixture)

A small interactive agent used to test Hansa's onboarding. It is deliberately ordinary: a chat loop on the
terminal, progress printed to stdout, and one tool that fetches a live web page. It does not read a task from
stdin or print JSON, so it cannot run in the sandbox until an adapter is written for it.

Run it locally with `python cli.py` and an `OPENAI_API_KEY`.

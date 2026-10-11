Run `python agent.py`. The process accepts one JSON task on stdin and emits one JSON result on stdout.
The normal task is `{"prompt":"Reply with OK."}`. `{"mode":"timeout"}` deliberately spawns a sleeping child and sleeps; the controller must kill both.
Other diagnostic modes: `isolation`, `overflow`, `invalid_json`, and `exit`.
Run this source only through the Docker runner. See [RUNNER.md](../../RUNNER.md).

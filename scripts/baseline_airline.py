"""Run upstream airline cases from an existing real GitHub import; never execute source on host."""
import argparse
import json

from backend.app.main import create_app
from backend.app.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("import_id")
    parser.add_argument("--repetitions", type=int, default=1,
                        help="Runs per case (1-5); use more than one when tools or models vary between runs.")
    args = parser.parse_args()
    settings = Settings.from_env()
    state = create_app(settings).app.state
    state.database.initialize()
    with state.database.connect() as db:
        row = db.execute("SELECT user_id, repository_name, connection_generation FROM repository_imports WHERE id=?",
                         (args.import_id,)).fetchone()
    if row is None or row["connection_generation"] == "local-fixture" or not row["repository_name"].endswith("/swarm"):
        raise SystemExit("Supply a real imported GitHub Swarm fork ID.")
    report = state.baselines.airline(row["user_id"], args.import_id, repetitions=args.repetitions)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

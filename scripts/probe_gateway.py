"""One bounded live call through the gateway; never print credentials."""
import asyncio
import argparse
import json
import time

import httpx

from backend.app.config import Settings
from backend.app.database import Database
from backend.app.main import create_app
from backend.app.gateway.service import GatewayService
from backend.app.sessions import token_hash


async def main(call_only=False):
    settings = Settings.from_env()
    database = Database(settings.database_path)
    database.initialize()
    gateway = GatewayService(settings, database)
    key = gateway.mint_key("live-haiku-probe", max_calls=1, max_spend_usd=None if call_only else 0.01,
                           expires_at=int(time.time()) + 120, litellm_model="claude-haiku")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(settings)),
                                     base_url="http://localhost") as client:
            response = await client.post("/gateway/v1/chat/completions",
                headers={"Authorization": "Bearer " + key},
                json={"model": "claude-haiku", "messages": [{"role": "user", "content": "Reply with OK."}],
                      "max_tokens": 16})
        summary = gateway.summarize_key(key)
        print(json.dumps({"http_status": response.status_code,
                          "spend_admission_enabled": not call_only,
                          "cost_header_recorded": summary["unknown_cost_calls"] == 0 and summary["calls"] == 1,
                          "ledger": summary,
                          "error": response.json().get("error") if response.status_code != 200 else None}, indent=2))
    finally:
        with database.connect() as db:
            db.execute("UPDATE gateway_keys SET revoked=1 WHERE key_hash=?", (token_hash(key),))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--call-only", action="store_true", help="Diagnostic only: one call without cost-estimate admission.")
    asyncio.run(main(parser.parse_args().call_only))

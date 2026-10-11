"""Minimal client for the Neatlogs MCP server (Streamable HTTP, JSON-RPC).

The project key can read and change the whole project, so it stays in this process. Callers get
parsed tool results or a NeatlogsError with a bounded message; provider bodies are never echoed.
"""
import json
import threading

import httpx

MAX_RESPONSE = 4 * 1024 * 1024
READ_TOOLS = {"ping", "whoami", "search_traces", "get_trace_context", "list_detections"}
WRITE_TOOLS = {"log_trace"}


class NeatlogsError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NeatlogsClient:
    def __init__(self, settings, transport=None):
        self.url, self.key = settings.neatlogs_mcp_url, settings.neatlogs_api_key
        self.transport = transport
        self.session, self.counter, self.lock = None, 0, threading.Lock()

    @property
    def enabled(self):
        return bool(self.key)

    def post(self, body, session):
        headers = {"Authorization": "Bearer " + self.key, "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if session:
            headers["mcp-session-id"] = session
        try:
            with httpx.Client(timeout=25, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                response = client.post(self.url, headers=headers, json=body)
        except httpx.HTTPError:
            raise NeatlogsError("Neatlogs could not be reached.") from None
        if len(response.content) > MAX_RESPONSE:
            raise NeatlogsError("Neatlogs response exceeded the size limit.")
        return response

    def messages(self, response):
        try:
            if "text/event-stream" in response.headers.get("content-type", ""):
                return [json.loads(line[5:]) for line in response.text.splitlines()
                        if line.startswith("data:") and line[5:].strip()]
            return [json.loads(response.text)] if response.text.strip() else []
        except ValueError:
            raise NeatlogsError("Neatlogs returned an unreadable response.") from None

    def open(self):
        response = self.post({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "hansa", "version": "0.1"}}}, None)
        if response.status_code in {401, 403}:
            raise NeatlogsError("Neatlogs rejected the project key.")
        session = response.headers.get("mcp-session-id")
        if response.status_code != 200 or not session:
            raise NeatlogsError(f"Neatlogs session could not be opened (status {response.status_code}).")
        self.post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
        return session

    def call(self, tool, arguments):
        if not self.enabled:
            raise NeatlogsError("Neatlogs is not configured.")
        if tool not in READ_TOOLS | WRITE_TOOLS:
            raise NeatlogsError("That Neatlogs tool is not used by this application.")
        for attempt in range(2):
            with self.lock:
                if self.session is None:
                    self.session = self.open()
                session, self.counter = self.session, self.counter + 1
                request_id = self.counter
            response = self.post({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                                  "params": {"name": tool, "arguments": arguments}}, session)
            # Sessions expire after an idle hour; open a fresh one once.
            if response.status_code in {400, 404} and attempt == 0:
                with self.lock:
                    if self.session == session:
                        self.session = None
                continue
            if response.status_code != 200:
                raise NeatlogsError(f"Neatlogs {tool} failed with status {response.status_code}.", response.status_code)
            for message in reversed(self.messages(response)):
                if isinstance(message, dict) and message.get("id") == request_id:
                    if "error" in message:
                        raise NeatlogsError(f"Neatlogs {tool} returned an error.")
                    try:
                        result = json.loads(message["result"]["content"][0]["text"])
                    except (KeyError, IndexError, TypeError, ValueError):
                        raise NeatlogsError(f"Neatlogs {tool} returned an unexpected result.") from None
                    if isinstance(result, dict) and result.get("error"):
                        raise NeatlogsError(f"Neatlogs {tool} refused the request: {str(result.get('errorCode') or 'error')[:60]}.")
                    return result
            raise NeatlogsError(f"Neatlogs {tool} returned no result.")
        raise NeatlogsError(f"Neatlogs {tool} failed after reopening the session.")

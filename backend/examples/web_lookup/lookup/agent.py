"""Answer a question, fetching web pages when the model asks for them."""
import json

from openai import OpenAI

from .tools import TOOL_SPEC, fetch_page

MODEL = "gpt-4o"
SYSTEM = ("You answer questions using the fetch_page tool when a fact needs checking on the web. "
          "Quote the page you used. Say so plainly when a page could not be fetched.")


class LookupAgent:
    def __init__(self, max_steps: int = 6):
        self.client = OpenAI()
        self.max_steps = max_steps
        self.history = [{"role": "system", "content": SYSTEM}]

    def ask(self, question: str) -> dict:
        self.history.append({"role": "user", "content": question})
        steps = []
        for step in range(self.max_steps):
            print(f"[agent] step {step + 1}")
            reply = self.client.chat.completions.create(model=MODEL, messages=self.history, tools=TOOL_SPEC)
            message = reply.choices[0].message
            self.history.append(message.model_dump(exclude_none=True))
            if not message.tool_calls:
                return {"answer": message.content, "steps": steps}
            for call in message.tool_calls:
                url = json.loads(call.function.arguments).get("url", "")
                page = fetch_page(url)
                steps.append({"tool": "fetch_page", "url": url, "characters": len(page)})
                self.history.append({"role": "tool", "tool_call_id": call.id, "content": page})
        return {"answer": None, "steps": steps}

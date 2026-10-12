<p align="center">
  <img src="docs/images/hansa-mark.svg" width="88" alt="Hansa logo">
</p>

<h1 align="center">Hansa</h1>

<p align="center"><b>An optimization engineer for your AI agent.</b></p>

<p align="center">
  <a href="https://hansa.sverma.online"><b>Live site</b></a> ·
  <a href="https://hansa.sverma.online/demo">Recorded run</a> ·
  <a href="https://hansa.sverma.online/judges">Evidence for each claim</a> ·
  <a href="https://cfo.ai/s/fG9t075-Bd4KFAHP">Business model</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black">
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white">
  <img alt="Neatlogs" src="https://img.shields.io/badge/Neatlogs-111827">
  <img alt="Entire" src="https://img.shields.io/badge/Entire-111827">
  <img alt="CFO.ai" src="https://img.shields.io/badge/CFO.ai-111827">
  <img alt="Tests" src="https://img.shields.io/badge/tests-297_pass-15734F">
</p>

<p align="center"><img src="docs/images/home.png" alt="The Hansa home page" width="900"></p>

Hansa was built for **neatHack 2026** by [@sonuv_dev](https://x.com/sonuv_dev), team Spectra.

## The problem

An AI agent has many parts: prompts, tools, memory, context and a model. Each part can make the agent slow, expensive or unreliable. To find the cause, you need an engineer who measures the agent and reads its code.

## What Hansa does

Hansa does the work of that engineer. It measures your agent, examines each part, and tests a fix. It gives you the fix only if the agent still gives the same answers.

## What Hansa examines

| Area | What Hansa looks for |
| --- | --- |
| **Prompt and context** | Text that the agent sends again on each call. A system prompt that is too large. |
| **Memory** | Data that the agent keeps between turns but does not use. A history that only grows. |
| **Tools** | Tool definitions that go with each call but are not used. The same tool call made two times. |
| **Agent design** | A step that only passes the request to a different agent. Loops that have no limit. |
| **Model choice** | A large model that does a simple job. |
| **Caching** | A stable part of the prompt that the provider can cache. |
| **Output** | Answers that are longer than the next step needs. |
| **Speed** | Calls that run one after the other but can run at the same time. |
| **Reliability** | No limit on turns or on answer length. A change that makes a task fail. |

## The steps

1. **Import.** Select a GitHub repository. Hansa copies one commit. The copy is read-only.
2. **Onboard.** The Hansa agent reads the code. It writes a small adapter that runs your agent.
3. **Baseline.** Hansa runs your tasks in a sandbox. It records each model call, its cost and its time.
4. **Find.** Hansa shows where the cost goes. It gives each finding with a file and a line.
5. **Test.** Hansa changes a private copy and runs the same tasks again.
6. **Result.** You get a patch, the measurements, and a brief for your coding agent.

<p align="center"><img src="docs/images/result.png" alt="A tested fix with before and after values" width="900"></p>

## Results

These results are from real agents. The checks are automatic. A person did not examine the answers.

So far, the fixes that Hansa tested changed the agent design. Hansa also reports findings in the other areas. For caching and model choice it gives an estimate, because the sandbox cannot measure them.

| Agent | Result |
| --- | --- |
| OpenAI Swarm, airline example | Hansa predicted 14.8% less cost. It measured **13.3% less cost and 22.7% fewer model calls** on 8 tasks. No task failed. Hansa accepted the fix. |
| OpenAI Swarm, earlier run | A fix removed 10% of the model calls, but one task failed. Hansa **rejected** the fix. |
| OpenAI Agents SDK, customer service example | A fix changed nothing. Hansa reported **no improvement**. |

## How it works

- **The model proposes. Code decides.** Hansa calculates the result from the measurements. The model cannot accept its own fix.
- **Your code runs in a sandbox.** The sandbox has no network of its own and no keys.
- **Each number comes from a recorded call.** Hansa records each model call in its gateway.

Hansa cannot measure some changes in the sandbox. Examples are a different model and prompt caching. For these changes, Hansa gives an estimate and labels it as an estimate.

## Tools

| Tool | Use |
| --- | --- |
| **Neatlogs** | Hansa records each sandbox run and each agent job as a trace. The app shows these traces. Hansa also reads the Neatlogs detections as leads. |
| **Entire** | Entire holds the repository and the recorded agent sessions for the commits. |
| **CFO.ai** | CFO.ai holds the business model. The model uses the measured costs. |
| **AWS EC2** | One server runs the API, the sandbox and the database. |
| **Vercel** | Vercel hosts the web interface. |
| **Python, FastAPI, SQLite** | The API, the agent and the data. |
| **Docker** | The sandbox for imported code. |
| **React, TypeScript, Vite, Tailwind CSS** | The web interface. |

## The sponsor tools

### Neatlogs

<p align="center"><img src="docs/images/neatlogs-dashboard.png" alt="The Neatlogs home page for Hansa: 337 sessions and a 3.6% error rate. An amber note from Hansa gives the real recorded spend." width="900"></p>

- **What Hansa records.** Each sandbox run is one trace. Each agent job is one trace. A trace shows each model call and each tool step. There are 337 traces.
- **How the product uses it.** Hansa reads each trace again to make sure that it arrived. The trace window in the app shows the Neatlogs steps and the Hansa cost for each call. During a deep hunt, the Hansa agent reads the Neatlogs detections as leads.
- **About the $0.00.** The amber box is a note from Hansa. Neatlogs calculates cost from the model name. Hansa sent a short model name that Neatlogs could not price. The real recorded spend is $13.30. New traces use a name that Neatlogs can price.

#### One incident from start to finish

The job is the onboarding of the OpenAI Agents SDK example. Neatlogs has a trace for each run.

| When | Result | Model calls | Cost |
| --- | --- | --- | --- |
| 11 Oct, 21:12 | **Failed** at the limit of 40 turns | 40 | $0.475 |
| 11 Oct, 21:24 | **Ready** | 18 | $0.233 |
| 12 Oct, 08:03 | **Ready**, after a provider timeout | 18 | $0.195 |

- **The cause.** The Hansa gateway refused requests that had fields it did not know. The agent used all 40 turns to try other methods.
- **The fix.** The gateway now removes those fields and sends the request. Twelve minutes later, the same job was complete in 18 calls at half the cost.
- **The next day.** The first model call timed out after one minute. Neatlogs shows it as a slow response and a failed execution. The job tried again and was complete.

<p align="center"><img src="docs/images/neatlogs-timeout-survived.png" alt="An onboarding trace in Neatlogs. The first model call has an error after one minute. The steps after it are successful." width="900"></p>

"Content withheld" in a trace means that Neatlogs refused the full text. Hansa then sends the trace again with times and token counts only.

### Entire

<p align="center"><img src="docs/images/entire-session.png" alt="A recorded Codex session in Entire: 2 checkpoints, 121 file changes and 171 tool calls" width="900"></p>

- **What it holds.** Entire holds the repository and the recorded agent sessions. [Open this session on Entire](https://entire.io/et/ouro/ouro/session/01a12981-647f-75f0-92e2-3f2bc6878d85).
- **How it helped.** More than one coding agent worked on Hansa. Entire gave each agent the context from the earlier sessions. I did not have to manage that context myself.
- **What it covers.** There are 11 checkpoints. One of them is `01M4N648YE33Y5BPN8XPQWGNZD` on commit `6482f84`. Run `entire checkpoint list` to see all of them.
- **What is next.** I will continue to use Entire for my development work.

### CFO.ai

<p align="center"><img src="docs/images/cfo-cost-simulator.png" alt="The Hansa cost simulator in CFO.ai: API fees of $1.39 for each first pass, with a measured range of $0.97 to $1.80" width="900"></p>

- **What it holds.** The business model: prices, the cost of each proof, a 12-month forecast and three scenarios. [Open the model](https://cfo.ai/s/fG9t075-Bd4KFAHP).
- **How it was used.** The model starts from measured costs. A full first pass on a small agent costs $0.97 to $1.80 in model fees.
- **What it showed.** The model provider bill is the largest cost. The server is a small cost.
- **The decision.** The customer pays their own model bill. Hansa charges a software fee: $149 each month for one proof, or $299 for three.
- **What is not measured.** Sandbox minutes, customer growth and prices are assumptions. No customer has paid.

## Run Hansa

The easiest method is the [live site](https://hansa.sverma.online). The [recorded run](https://hansa.sverma.online/demo) needs no account.

To run Hansa on your computer, you need Python 3.12, [uv](https://docs.astral.sh/uv/), Node 20 and Docker.

```sh
# Start the API
cd backend
uv sync --locked
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log

# Start the web interface in a second terminal
cd frontend
npm install
npm run dev

# Run the tests
cd backend && uv run pytest
```

Put your settings in a `.env` file at the top of the repository. Use [backend/.env.example](backend/.env.example) as the template. For more instructions, see [backend/docs/SETUP.md](backend/docs/SETUP.md).

## Folders

| Folder | Contents |
| --- | --- |
| `backend/` | The API, the Hansa agent, the sandbox and the tests |
| `frontend/` | The web interface |
| `deploy/` | The server setup |
| `docs/` | Screenshots |

## Limits

- The proof is only as good as the tasks. Most results use 2 to 8 tasks.
- Hansa supports Python agents that use the OpenAI chat format.
- Hansa runs one job at a time.
- The costs come from the model provider. They are not compared with an invoice.

## Credits

Hansa was built with [Neatlogs](https://neatlogs.com), [Entire](https://entire.io) and [CFO.ai](https://cfo.ai). It was tested on the OpenAI [Swarm](https://github.com/openai/swarm) and [Agents SDK](https://github.com/openai/openai-agents-python) examples.

# Deploying Hansa

Proposed layout, not yet exercised: nothing here has been run against a real server.

- **Frontend** on Vercel at `https://hansa.yourdomain.com`.
- **API and sandbox** on one EC2 instance at `https://hansa-api.yourdomain.com`.

The browser only ever talks to the Vercel address. [frontend/vercel.json](../frontend/vercel.json) passes `/auth/*` and `/github/*` through to the API, so sign-in cookies and the app's relative requests work without cross-site settings.

Replace `HANSA_API_HOST` in `frontend/vercel.json` and `deploy/Caddyfile` with the API's name before deploying.

## Hackathon AWS limits

From [hackathon.md](../hackathon.md): `us-east-1` only, the existing `Hackathon_VPC`, one EC2 instance per IAM user, sizes `t2`/`t3`/`t3a` from `nano` to `large`, each EBS volume at most 50 GB, one shared $25 allowance. Stop the instance when judging ends.

A `t3.medium` (4 GB) runs the API and one sandbox at a time; a `t3.large` (8 GB) leaves more room. Use a 30 to 50 GB volume: sandbox images are tens of megabytes each and are pruned after every build.

## DNS, on your domain

| Name | Type | Points to |
| --- | --- | --- |
| `hansa` | CNAME | the target Vercel shows when you add the domain to the project |
| `hansa-api` | A | the instance's Elastic IP |

## Server

```sh
sudo apt-get update && sudo apt-get install -y docker.io caddy git
sudo useradd --system --create-home --groups docker hansa
sudo mkdir -p /opt/hansa && sudo chown hansa /opt/hansa
sudo -u hansa git clone <repository> /opt/hansa
cd /opt/hansa/backend && sudo -u hansa sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh && ~/.local/bin/uv sync --locked'
```

Create `/opt/hansa/.env` as [README.md](../README.md) describes, with these hosted values:

```sh
APP_URL=https://hansa.yourdomain.com
FRONTEND_ORIGIN=https://hansa.yourdomain.com
AUTH_COOKIE_SECURE=true
```

`APP_URL` is the Vercel address, not the API's, because sign-in callbacks return through Vercel.

Then:

```sh
sudo cp /opt/hansa/deploy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl restart caddy
sudo cp /opt/hansa/deploy/hansa-api.service /etc/systemd/system/ && sudo systemctl enable --now hansa-api
```

Open ports 80 and 443 in the instance's security group. Port 8000 stays closed; only Caddy reaches it.

## Sign-in callbacks to register

Use the Vercel address in each provider's settings:

- GitHub sign-in: `https://hansa.yourdomain.com/auth/github/callback`
- Google sign-in: `https://hansa.yourdomain.com/auth/google/callback`
- GitHub App: callback and webhook addresses under `https://hansa.yourdomain.com/github/` (see [GITHUB_IMPORT.md](../backend/docs/GITHUB_IMPORT.md) for the exact paths)

## Frontend

In Vercel, import the repository, set the root directory to `frontend`, and add `hansa.yourdomain.com` under Domains. The build command and output folder are Vite's defaults (`npm run build`, `dist`).

## Keeping it closed

- **Invite list.** Set `AUTH_ALLOWED_EMAILS=you@example.com,judge@example.com` in `.env` and only those addresses can sign in, by GitHub, Google or password. Everyone else is told the server is invitation-only; the recorded demo stays open. Leave it unset and anyone may sign in.
- **Public paths.** The Caddyfile passes only `/auth/*` and `/github/*` to the API. The model gateway and everything else answer 404 from outside; the sandbox reaches the gateway over a local relay.
- **No API reference.** With `AUTH_COOKIE_SECURE=true` the API stops serving `/docs`, `/redoc` and `/openapi.json`.
- **`.env`.** `chmod 600 /opt/hansa/.env`, owned by `hansa`. It is ignored by git; never copy it into the repository folder on Vercel.
- **Firewall.** Open 80 and 443 to everyone and 22 to your own IP only. Leave 8000 closed.
- **Push only `main`.** The Entire checkpoint branches hold coding-session transcripts. They are not part of `main`; do not push them to a public remote.
- **Frontend policy.** `frontend/vercel.json` sends a content security policy that allows scripts only from the site itself, plus the one inline script in `index.html` by hash. After editing that script, run `npm run build && node scripts/check-csp.mjs` and update the hash it prints.

## Before opening it to others

- Anyone who signs in can start runs, which spend the model allowance and execute their repository in the sandbox. Decide who may sign in before sharing the address.
- When the model allowance runs out, starting a run is refused with a plain message and saved results stay readable.
- Hansa runs one job at a time; a second request is refused with what is running, not queued.

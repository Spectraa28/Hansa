# Deploying Hansa

Proposed layout, not yet exercised: nothing here has been run against a real server.

- **Frontend** on Vercel at `https://hansa.svema.online`.
- **API and sandbox** on one EC2 instance at `https://hansa-api.svema.online`.

The browser only ever talks to the Vercel address. [frontend/vercel.json](../frontend/vercel.json) passes `/auth/*` and `/github/*` through to the API, so sign-in cookies and the app's relative requests work without cross-site settings.

`frontend/vercel.json` already points at `hansa-api.svema.online`. `deploy/Caddyfile` keeps a placeholder that `setup-server.sh` fills in from the name you pass it.

## Hackathon AWS limits

From [hackathon.md](../hackathon.md): `us-east-1` only, the existing `Hackathon_VPC`, one EC2 instance per IAM user, sizes `t2`/`t3`/`t3a` from `nano` to `large`, each EBS volume at most 50 GB, one shared $25 allowance. Stop the instance when judging ends.

A `t3.medium` (4 GB) runs the API and one sandbox at a time; a `t3.large` (8 GB) leaves more room. Use a 30 to 50 GB volume: sandbox images are tens of megabytes each and are pruned after every build.

## DNS, on your domain

| Name | Type | Points to |
| --- | --- | --- |
| `hansa` | CNAME | the target Vercel shows when you add the domain to the project |
| `hansa-api` | A | the instance's Elastic IP |

## Server

On a fresh Ubuntu 24.04 instance, copy [setup-server.sh](setup-server.sh) over and run it:

```sh
sudo bash setup-server.sh https://github.com/<you>/<repository>.git hansa-api.svema.online
```

It installs Docker, Caddy and the Python environment, clones `main`, pulls the sandbox base image, writes the Caddy config for your API name, adds swap and a nightly database backup (seven kept, under `/var/backups/hansa`), and installs the API service. It writes no secrets and does not start the API until `/opt/hansa/.env` is filled in.

Create `/opt/hansa/.env` as [README.md](../README.md) describes, with these hosted values:

```sh
APP_URL=https://hansa.svema.online
FRONTEND_ORIGIN=https://hansa.svema.online
AUTH_COOKIE_SECURE=true
```

`APP_URL` is the Vercel address, not the API's, because sign-in callbacks return through Vercel. Then `sudo systemctl start hansa-api`.

Open ports 80 and 443 in the instance's security group. Port 8000 stays closed; only Caddy reaches it. To deploy a later change, run the script again: it pulls `main` and restarts the API. Do not do that while a job is running.

## Sign-in callbacks to register

Use the Vercel address in each provider's settings:

- GitHub sign-in: `https://hansa.svema.online/auth/github/callback`
- Google sign-in: `https://hansa.svema.online/auth/google/callback`
- GitHub App: callback and webhook addresses under `https://hansa.svema.online/github/` (see [GITHUB_IMPORT.md](../backend/docs/GITHUB_IMPORT.md) for the exact paths)

## Frontend

In Vercel, import the repository, set the root directory to `frontend`, and add `hansa.svema.online` under Domains. The build command and output folder are Vite's defaults (`npm run build`, `dist`).

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

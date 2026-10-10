# GitHub repository import

Status: all 45 backend regression tests passed, including mocked import tests. Real GitHub sign-in and App connection succeeded. SQLite confirms the ready import of `Spectraa28/VaultLearn` at fixed SHA `896d8802cc5e27a88fc1be691f491d950ed26bbe` with saved inspection findings; the user confirmed the UI flow works. See [REPOSITORY_INSPECTION.md](REPOSITORY_INSPECTION.md) for inspection/configuration boundaries. No execution sandbox is implemented, and no imported code was executed.

## GitHub App configuration

Create a **GitHub App**, separate from the OAuth App used for sign-in:

- Repository permissions: **Contents: read**, **Metadata: read**, with no additional permissions. The backend checks the App permissions when starting a connection.
- Callback URL: `http://localhost:8000/github/callback` locally, or the exact hosted `APP_URL` plus `/github/callback`.
- Setup URL: `APP_URL` plus `/github/connection`. Leave **Request user authorization during installation** off: the explicit Connect action owns state and PKCE. Installation callbacks are not treated as proof of access.
- Enable expiring user access tokens. Users install the App on their account or organization and choose **Only select repositories**. Organization owners may need to approve installation; the API cannot bypass approval.
- Hosted webhook URL: `APP_URL` plus `/github/webhook`, with a random secret. Installation, repository-selection, and authorization-revocation events are handled.

Fill `GITHUB_APP_ID`, `GITHUB_APP_CLIENT_ID`, `GITHUB_APP_CLIENT_SECRET`, `GITHUB_APP_PRIVATE_KEY_PATH`, and `GITHUB_APP_CALLBACK_URL` in the ignored server `.env`. Store the downloaded RSA private key in ignored `var/github-app.pem` or a private location outside the checkout. All required settings must be present to enable the connector. No real App or credentials have been configured here.

Generate a separate encryption key locally, then set `GITHUB_TOKEN_ENCRYPTION_KEY`:

```sh
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

This is a setup instruction, not an executed command. Keep the key outside SQLite, preserve it across restarts, and back it up separately. Changing it without migrating encrypted credentials requires reconnecting. Set `GITHUB_WEBHOOK_SECRET` to another random secret; hosted imports require at least 32 characters.

## API flow

All endpoints except the signed webhook require application login. Every POST/DELETE except the webhook requires the current `X-CSRF-Token`; send cookies with `credentials: "include"`.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/github/connection` | Connection status and stable GitHub user ID; no tokens |
| POST | `/github/connect` | Session-bound state/PKCE; return `authorization_url` and `installation_url` |
| GET | `/github/callback` | Consume state, connect the current account, redirect to connection status |
| GET | `/github/installations` | Verified accessible installations and App installation URL |
| GET | `/github/repositories?installation_id=...` | Repositories accessible to both the user and App |
| GET | `/github/branches?installation_id=...&repository_id=...` | Branches, current SHAs, and default branch |
| POST | `/github/imports` | Resolve selected/default branch to a SHA and persist a queued import; `202` |
| GET | `/github/imports` | Current account's persisted imports |
| GET | `/github/imports/{id}` | Result, SHA, warnings, counts, and safe failure reason |
| DELETE | `/github/imports/{id}` | Cancel an import or delete source; retain a `deleted` record |
| DELETE | `/github/connection` | Erase stored tokens/state and cancel pending imports |
| POST | `/github/webhook` | Validate HMAC-SHA256 signature and deduplicate delivery IDs |

Installations, repositories, branches, and imports accept `page` and `per_page` (1–100), returning `has_next`. Access verification constructs supported GitHub endpoints rather than following pagination URLs. Very large access lists and Git trees return listing-limit failures.

Frontend sequence: log in → POST Connect → navigate to `authorization_url` → navigate to `installation_url` to grant selected access → refresh installations/repositories → select a branch → POST import → poll its result. Google and email users use this same flow. The callback currently shows JSON; no frontend exists yet.

Example import body:

```json
{"installation_id": 200, "repository_id": 300, "branch": "main"}
```

Omit `branch` to use the default branch. The backend resolves and stores the exact commit **before** enqueueing; the worker downloads that SHA even if the branch moves. It rechecks user access before downloading and immediately before publishing source. A browser-supplied installation ID never proves permission.

Imports move through `queued → downloading → ready / failed`. Browser refreshes read the same SQLite record. Startup resumes queued work, marks interrupted downloads failed with a retry instruction, and removes partial staging files and orphaned failed snapshots. Failure codes cover access denial or pending organization approval, expired authorization, empty repositories, unavailable branches, rate limits, archive limits, invalid archives, and interruption. GitHub rate-limit responses include `Retry-After`.

## Source and credential boundaries

- Connections store stable GitHub IDs, verified installation IDs, status, and Fernet-encrypted user/refresh credentials. Email matching never connects or merges accounts. User tokens refresh under a lock. Installation tokens are generated for one repository with read permissions, expire after one hour, and stay in memory.
- SQLite records import ownership, repository ID/name, branch, SHA, internal snapshot location, status, timestamps, and failure reasons. Source lives in `var/imports/<application-user-id>/<import-id>/` with private directories/files. API results omit filesystem paths and credentials.
- Archive redirects must use HTTPS `codeload.github.com` and match the requested repository and SHA. Bearer tokens are not forwarded to that host. Source is published atomically and temporary downloads are removed.
- Defaults: 100 MiB download, 500 MiB extracted source, 20,000 archive entries, 120-second operation deadline, and 15-second network idle timeout. Decompressed headers/padding are bounded too. Links, special files, traversal, duplicate paths, excessive depth, and `.git` metadata are rejected. Files are stored without executable permissions.
- Admission allows five queued/downloading/ready imports per account and 100 queued/downloading imports across the controller. Delete retained source to release account capacity. These limits do not reserve global disk space.
- Submodules are detected through Git tree entries and `.gitmodules` but never fetched. Git LFS pointers and `filter=lfs` attributes produce warnings; LFS objects are not separately fetched. A ready snapshot with these warnings is incomplete for workflows that need those dependencies. GitHub archive settings may include LFS content; byte limits still apply.
- Import never installs dependencies or executes source. Credentials and original snapshots must stay outside the later execution sandbox. No source-serving static directory is configured.
- Disconnect erases local authorization and stops new imports; ready snapshots remain until the user deletes them. Users can separately revoke App authorization or uninstall it in GitHub settings. Signed revocation/removal webhooks cancel active imports and stop use of revoked user credentials. Ready source remains owner-deletable.
- Run **one API process/worker**. Do not use `--workers` greater than one: startup recovery assumes sole ownership of this queue. Distributed leases and execution workers are deferred.

Use the README's `--no-access-log` startup command. Outbound HTTP diagnostic logs are limited to warnings to keep codes and signed archive URLs out of request logs. GitHub import endpoints are not traced to Neatlogs.

## Verification boundaries

[backend/tests/test_github_import.py](backend/tests/test_github_import.py) contains passing mocked boundary/regression tests, not evidence of real App repository access. The user authorized testing and all 37 backend tests passed outside the sandbox. Real private repositories, organization approval, pagination, token expiration, webhook delivery, and archives still need separate checks against an actual configured App.

References: [user authorization](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app), [accessible installations/repositories](https://docs.github.com/en/rest/apps/installations), [archive API](https://docs.github.com/en/rest/repos/contents#download-a-repository-archive-tar), [installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app), [JWT authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app), and [webhook validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).

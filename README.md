# Pro Resolutions quote intake

The website and quote API run together on the existing Render service:
https://proresolutions.onrender.com

The form collects service, quantity, preferred timing, bird protection, name,
email, property locations, and optional notes. A received request is saved in
PostgreSQL before the visitor sees a receipt. The outbox worker then creates a
task in ClickUp's **work** list (`901421893621`).

## Current status — October 7, 2026

The prepared website and backend were uploaded through the GitHub browser
interface to `aceorb596/proresolutions`, branch `main`. The existing Render
service now builds from that repository and is live at the unchanged URL.
Runtime commit: `375be25435c485baa0362980379b2f4408232e04`.

The existing ae-world database and ClickUp integration are configured using
server-side environment variables. No duplicate resources were created.
The timing dropdown markup was corrected without changing labels or prices.

## Existing resources

| Resource | Identity |
| --- | --- |
| GitHub source | `aceorb596/proresolutions`, branch `main` |
| Upstream source base | `e8c2b87f7a98eade35451e64bba4c989aa186768` |
| Render workspace | Chadlie's workspace, `tea-db18fo0u01pc73daljbg` |
| Render web service | `proresolutions`, `srv-db2qcqs9v7es739ssijg` |
| PostgreSQL | `ae-world`, `dpg-db18pp2d0e5s73el2k8g-a` |
| Existing ClickUp service | `ae-clickup-loop-v2`, `srv-db1bdjjncjis73c1efl0` |
| ClickUp destination | [work](https://app.clickup.com/90141732851/v/l/li/901421893621) |

## Deployment configuration

The existing service was configured directly in Render Dashboard; no new
Blueprint or service was created. `render.yaml` records the intended settings.

- Repository: `https://github.com/aceorb596/proresolutions`, branch `main`.
- Build: `pip install -r backend/requirements.txt`.
- Start: `gunicorn 'backend.app:create_app(start_worker=True)' --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60`.
- Health check: `/ready`; manual deployments retained.
- `DATABASE_URL` uses ae-world's internal connection; `CLICKUP_TOKEN` reuses the
  existing integration token. Existing `ADMIN_TOKEN` retained.
- Legacy release environment variables remain unused by this build.
- Database external access remains closed; all secrets stay in Render.

## Website and API

`GET /` serves the site. Only `app.js`, `style.css`, and `mark.svg` are public
files. Backend code, schema, configuration, and README are not served.

`GET /api-config.js` enables the same-origin API when database and ClickUp clients
are configured. Otherwise the page explicitly remains a request-summary preview.
A standalone static copy also stays in preview.

`GET /health` checks process liveness. `GET /ready` checks database connectivity
and presence of ClickUp configuration. Render uses `/ready` for deployment
health. Readiness does not prove the token can create a ClickUp task; verify the
actual handoff separately.

## Request and delivery behavior

- Server prices are authoritative: $125 per stairwell clean; $1,250 per building
  for 5+ buildings. Bird protection is separately quoted; its bundle discount
  applies to the building offer.
- Each `POST /api/quotes` has a UUIDv4 `Idempotency-Key`. Identical retries return
  the saved receipt. Reusing an ID with different details is rejected. Browser
  session storage contains only the ID and a payload digest.
- One PostgreSQL row stores the inquiry and ClickUp delivery state. The worker
  commits its claim before sending. Uncertain delivery is reconciled by an exact
  request marker and may become `needs_review`; it is never blindly resent.
- ClickUp tasks include the next action: confirm scope and access, then prepare
  the quote. The `[ae-generated]` marker prevents the older experimental webhook
  from adding duplicate continuations. The production entry point starts
  `create_app(start_worker=True)`.
- A failure preserves entered details. Receipt appears only after API
  acknowledgement. The form does not book a time or take payment.
- Limits: 16 KiB body, validated fields, a honeypot, 5 requests per email per
  hour, and 100 total per hour. Origin filtering is not bot authentication.

## Local verification

Use Python 3.12:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt pytest
.venv/bin/python -m pytest -q
node --check app.js
```

The suite covers validation/pricing, failure/replay responses, delivery and
reconciliation, public routes, private-file isolation, and preview mode.
Database and ClickUp operations use test doubles; a passing local suite is not
evidence of a live external handoff.

For interactive development, configure a dedicated test database and ClickUp
list, set `DATABASE_URL`, `CLICKUP_TOKEN`, `CLICKUP_LIST_ID`, `ALLOWED_ORIGINS`,
and `ADMIN_TOKEN`, then run `python -m backend.app`.

## Live acceptance check — passed October 7, 2026

- Local test suite: 26 passed.
- Live browser submitted a synthetic five-building quote with bird protection
  and Planning ahead timing. Cleaning subtotal was $6,250; bird protection
  remained separately quoted and eligible for the bundle discount.
- Receipt: `e8a1527b-8cab-4f91-9bb5-1b9c3dd1ee35`.
- Matching ClickUp task: `86bceux8c`, explicitly labeled synthetic and closed.
- Identical POST replay returned HTTP 200 and the same saved receipt.
  ClickUp contained exactly one task for this request.
- `/health` and `/ready` returned HTTP 200. Unauthenticated admin access
  returned 401; backend source, render.yaml and .env returned 404.
- Persistence was verified through saved-receipt replay. Direct external SQL
  inspection was not used because database external access is closed.

## Operations and current limits

`GET /api/admin/quotes` returns the latest 100 inquiries and requires
`Authorization: Bearer <ADMIN_TOKEN>`.
`PATCH /api/admin/quotes/<id>` accepts an explicit `outcome`: `new`, `quoted`,
`booked`, or `lost`. Outcomes do not automatically mirror ClickUp status.

For `needs_review`, check ClickUp for the exact request UUID before any retry.
An authorized database operator must attach the existing task or reset a request
only after confirming it was not delivered. There is no public retry control.

The free `ae-world` database expires **November 3, 2026**. Decide its replacement
or upgrade before relying on it for customer inquiries. Free Render web services
sleep after inactivity; pending handoffs resume when the service wakes.
No paid plan was selected or changed in this work.

## Official documentation

- [Blueprint specification](https://render.com/docs/blueprint-spec)
- [Blueprint adoption](https://render.com/docs/infrastructure-as-code)
- [Environment variables](https://render.com/docs/configure-environment-variables)
- [Free service limits](https://render.com/docs/free)

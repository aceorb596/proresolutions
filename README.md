# Pro Resolutions quote intake

The website and quote API run together on the existing Render service:
https://proresolutions.onrender.com

The form collects service, quantity, preferred timing, bird protection, name,
email, property locations, and optional notes. A received request is saved in
PostgreSQL before the visitor sees a receipt. The outbox worker then creates a
task in ClickUp's **work** list (`901421893621`).

## Current status — October 7, 2026

This source was recovered from the earlier saved implementation and updated for
the existing web service. It has **not** been pushed or deployed by this task.
GitHub rejects branch creation with HTTP 403, "Resource not accessible by
integration". Its connected installation inventory is empty. Render's connector
cannot link existing secrets or change service build settings.

Fresh live checks returned 200 from `/health` and 503 from `/ready`.
The deployed build expands a release stored in environment variables, so pushing
GitHub source alone does not replace that implementation.

## Existing resources

| Resource | Identity |
| --- | --- |
| GitHub source | `aceorb596/pro-solutions-website`, branch `main` |
| Upstream source base | `e8c2b87f7a98eade35451e64bba4c989aa186768` |
| Render workspace | Chadlie's workspace, `tea-db18fo0u01pc73daljbg` |
| Render web service | `proresolutions`, `srv-db2qcqs9v7es739ssijg` |
| PostgreSQL | `ae-world`, `dpg-db18pp2d0e5s73el2k8g-a` |
| Existing ClickUp service | `ae-clickup-loop-v2`, `srv-db1bdjjncjis73c1efl0` |
| ClickUp destination | [work](https://app.clickup.com/90141732851/v/l/li/901421893621) |

## Finish the existing deployment

1. Restore GitHub connector write access to the repository. Review and merge this
   source on `main`; it contains no credentials or customer data.
2. Open the [existing Render service](https://dashboard.render.com/web/srv-db2qcqs9v7es739ssijg).
   Use its controlling Blueprint if it has one. Otherwise use the Dashboard
   workflow to generate/adopt a Blueprint for this existing service.
   `render.yaml` supplies the desired settings.
3. Review Render's change plan: update `srv-db2qcqs9v7es739ssijg`, create no
   services, databases, or disks, and keep the current free plan. A new suffixed
   `proresolutions-*` service is a different resource; do not apply that plan.
   The configuration retains manual deployments.
4. The Blueprint links `DATABASE_URL` to `ae-world`'s internal connection string
   and `CLICKUP_TOKEN` to the existing variable on `ae-clickup-loop-v2`.
   It preserves an existing `ADMIN_TOKEN`, generating one only if absent.
   Database external access can remain closed.
5. Confirm the saved build command is
   `pip install -r backend/requirements.txt`. The old release extraction must
   no longer run. Omitted `PRORESOLUTIONS_RELEASE` and `PRORESOLUTIONS_SHA256`
   variables may remain in Render; this code and normal build do not use them.
6. Apply the reviewed update and run the acceptance checks below. A YAML change
   takes effect only after Render adopts/syncs that Blueprint.

If adopting a Blueprint is unavailable, configure those same two connections
inside Render's Environment settings and copy the remaining settings from
`render.yaml` into the existing service. Keep secrets in Render; do not paste
them into GitHub, a customer form, or chat.

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

## Live acceptance check — pending

1. Confirm `/` and frontend assets return 200; `/ready` must return
   `{"ready":true}`.
2. Send one clearly marked synthetic form inquiry: five buildings, bird
   protection, `test@example.com`, and notes "Synthetic test — do not contact".
   Expected cleaning subtotal: $6,250. Bird protection remains separately quoted.
3. Check one saved request through the protected admin endpoint and one matching
   `[PR <request UUID>]` task in ClickUp **work**.
4. Replay the same POST with the same ID. Expect HTTP 200, the same receipt, and
   no additional database row or ClickUp task.
5. Keep the test task visibly labeled and close it after review.

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

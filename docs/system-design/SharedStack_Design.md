# SharedStack — Cross-Domain Foundation

> Detailed design for the single PM-owned CDK stack that every Kismet domain depends on.
> Source of truth: [`infra/stacks/shared_stack.py`](../../infra/stacks/shared_stack.py) + [`infra/app.py`](../../infra/app.py)
> Last verified: Apr 16, 2026

---

## 1. Purpose

`SharedStack` is the single foundational stack deployed **once, by the PM**, before any domain team runs `cdk deploy`. It exists so that the six domain stacks (D1 Identity, D2 Discovery, D3 Messaging, D4 Moderation, D5 Notifications, D6 Analytics) don't each spin up their own Cognito pool, REST API, event bus, or photo bucket — instead they all wire into the same "facility-level" resources.

Keeping these resources in one stack has two practical effects:
1. **One auth plane, one API host, one event bus.** The frontend has a single Cognito user pool ID and a single `/dev` API URL to bind to. Events published by D2 are visible to D3/D5/D6 without any cross-bus routing.
2. **One blast radius, one owner.** Anything cross-cutting (CORS, authorizer, photo CDN) changes in one place. Domain teams never touch Shared without PM review.

The trade-off — and the source of most of the gotchas in §5 — is that every domain stack becomes a **consumer of Shared's CloudFormation exports**, which makes updating Shared after the fact harder than updating a domain.

---

## 2. Architecture

```
                     ┌──────────────────────────────────┐
                     │           SharedStack            │
                     │                                  │
   Cognito UserPool ─┤  kismet-user-pool  ──► Authorizer│─┐
   (self sign-up)    │                                  │ │
                     │  API Gateway  kismet-api / dev ──┼─┼──► domain stacks
                     │                                  │ │    attach routes
   EventBridge ──────┤  kismet-events bus  ─────────────┼─┼──► publishers + rules
                     │                                  │ │
   S3 photos ────────┤  kismet-photos-{acct}-dev  ──┐   │ │
                     │                              ▼   │ │
                     │  CloudFront (HTTPS, gzip, cached)│─┴─► Photo Service (D1)
                     │                                  │
   S3 analytics ─────┤  kismet-analytics-{acct}-dev     │──► D6 / analytics jobs
                     │                                  │
   Kinesis ──────────┤  DISABLED (self.activity_stream  │    D6 falls back to
                     │   = None — see §5.1)             │    direct-write
                     │                                  │
   SNS ──────────────┤  kismet-health-alerts            │──► Health Monitor
                     └──────────────────────────────────┘
```

`app.py` instantiates `SharedStack` first, then passes the reference into every domain: `DomainNStack(app, "KismetDomainN", shared=shared, env=env)`.

---

## 3. Resources Deep-Dive

### 3.1 Cognito UserPool — `kismet-user-pool`

| | |
|---|---|
| **Construct ID** | `UserPool` |
| **Sign-in** | email alias |
| **Self sign-up** | enabled |
| **Auto-verify** | email |
| **Password policy** | min length 8, uppercase not required, symbols not required |
| **Removal policy** | `DESTROY` |

Self sign-up is on because the demo flow has users register themselves from the web client — there is no invite gate. Auto-verify on email is what lets Cognito send the confirmation code without an admin step.

The relaxed password policy (no uppercase, no symbols) is a deliberate demo-only choice: it keeps the barrier low for reviewers creating throwaway accounts. Production would tighten this.

`RemovalPolicy.DESTROY` means `cdk destroy KismetShared` will take the user pool with it — fine for a teardown-capable demo account, not fine for anything with real users.

### 3.2 Cognito App Client — `kismet-web-client`

Attached to the user pool via `user_pool.add_client(...)`. Auth flows enabled:
- `USER_PASSWORD_AUTH` — used by the web client's login form (username+password direct)
- `USER_SRP_AUTH` — used by Amplify/`amazon-cognito-identity-js` when it chooses SRP

Both are enabled so the frontend library is free to pick either. No client secret is configured (this is a public SPA client).

### 3.3 API Gateway REST API — `kismet-api`

| | |
|---|---|
| **Construct ID** | `Api` |
| **Type** | `RestApi` (edge-optimized, default) |
| **Stage** | `dev` (via `deploy_options.stage_name`) |
| **CORS preflight** | `ALL_ORIGINS`, `ALL_METHODS`, headers `Content-Type, Authorization` |
| **Authorizer** | `CognitoUserPoolsAuthorizer` bound to the user pool above |

Every domain stack re-hydrates this API via `apigateway.RestApi.from_rest_api_attributes(...)` and mounts its routes on `api.root`. The `CognitoAuthorizer` is re-used as-is — each domain route that opts into auth references `shared.authorizer`.

The `dev` stage exists because we only ship one environment for the demo. The `ALL_ORIGINS` CORS is a demo-grade shortcut; production would allow-list the frontend origin explicitly.

### 3.4 EventBridge Bus — `kismet-events`

Custom bus (`events.EventBus`, name `kismet-events`). Every cross-domain event flows here — `profile.completed`, `swipe.created`, `match.created`, `message.sent`, `report.created`, `user.banned`, `user.deleted`, etc. Event shapes are catalogued in [`event-schema.json`](./event-schema.json).

Publishing and subscription are wired through the `KismetService` construct (see §4): any service with `publish_events=True` gets `events:PutEvents` + an `EVENT_BUS_NAME` env var, and any `consume_events=[...]` declaration creates a `events.Rule` on this bus targeting the Lambda.

### 3.5 S3 Photos Bucket — `kismet-photos-{account}-dev`

| | |
|---|---|
| **Construct ID** | `PhotosBucket` |
| **CORS** | `GET` + `PUT`, all origins, all headers |
| **Public read** | `public_read_access=True` |
| **BlockPublicAccess** | all four flags set to `False` (bucket ACLs + policies allowed public) |
| **Removal policy** | `DESTROY` with `auto_delete_objects=True` |

The bucket is intentionally publicly readable for the MVP — the frontend renders profile photos as plain `<img src="https://<cdn>/...">`. CORS `PUT` is present so the frontend can perform browser-direct uploads via presigned URLs issued by Photo Service (D1).

The `{account}` interpolation (`self.account`) keeps the bucket name globally unique per AWS account without hard-coding it. The `-dev` suffix lines up with the `dev` API stage; a prod stack would pick its own suffix.

See §5.4 for why "public read" is demo-only.

### 3.6 CloudFront Distribution — photos CDN

Wraps the photos bucket via `origins.S3BucketOrigin(self.photos_bucket)`. Default behavior:

- `viewer_protocol_policy=REDIRECT_TO_HTTPS`
- `allowed_methods=ALLOW_GET_HEAD_OPTIONS` (read-only; writes go direct to S3 via presigned PUT)
- `cache_policy=CACHING_OPTIMIZED`
- `compress=True` (gzip for text/SVG metadata files — most payload is JPEG which is already compressed)

The computed domain is exposed as `self.photos_cdn_base_url = f"https://{...distribution_domain_name}"` and handed to Photo Service (D1) so its DB records store CDN URLs instead of raw S3 URLs.

### 3.7 S3 Analytics Bucket — `kismet-analytics-{account}-dev`

Plain bucket, no CORS, no public access, `DESTROY` + `auto_delete_objects=True`. Destination for D6 analytics output (batch exports, offline reports). No lifecycle rules configured yet.

### 3.8 Kinesis Data Stream — **disabled**

The CDK code currently has the Kinesis block commented out and sets:

```python
self.activity_stream = None  # Kinesis not yet available
```

The intent (per the comment in `shared_stack.py`) is a single-shard `kismet-activity-stream` re-enabled once the new AWS account's Kinesis quota is granted. Today, downstream D6 Activity Logger detects `activity_stream is None` and falls back to direct DynamoDB writes. The `ActivityStreamArn` CfnOutput is guarded by `if self.activity_stream:` so the export simply doesn't exist on this account.

See §5.1.

### 3.9 SNS Topic — `kismet-health-alerts`

Plain `sns.Topic` named `kismet-health-alerts`. Subscribed to by the Health Monitor Lambda (outside this stack). No subscriptions are created in Shared itself — Shared only owns the topic.

---

## 4. Integration Patterns

### 4.1 Cross-stack handoff via Python reference

`app.py` passes `shared=SharedStack` into each domain stack. Inside each domain stack, `shared.user_pool`, `shared.authorizer`, `shared.event_bus`, `shared.photos_bucket`, `shared.photos_cdn_base_url`, `shared.health_alerts_topic` are consumed directly as CDK constructs. CDK turns the cross-stack references into CloudFormation exports/imports under the hood — that's what produces the deletion constraints in §5.3.

### 4.2 REST API re-hydration

Rather than threading `shared.api` as a live construct (which couples synth order tightly), each domain re-imports the API by attributes:

```python
apigateway.RestApi.from_rest_api_attributes(
    self, "ImportedApi",
    rest_api_id=shared.api.rest_api_id,
    root_resource_id=shared.api.rest_api_root_resource_id,
)
```

The resulting `IRestApi` is passed into `KismetService(..., api=imported_api, authorizer=shared.authorizer, ...)`. `KismetService` walks the path parts and `add_resource` / `add_method` under `api.root`, wiring the Cognito authorizer in for any route with `auth: True`.

### 4.3 EventBridge re-hydration

Same pattern for the bus:

```python
events.EventBus.from_event_bus_name(
    self, "ImportedBus",
    event_bus_name=shared.event_bus.event_bus_name,
)
```

Passed to `KismetService(..., event_bus=imported_bus, publish_events=..., consume_events=[...])`. `KismetService` grants `PutEvents` and sets `EVENT_BUS_NAME` on publish, and creates `events.Rule`s on this bus for each consumed detail-type.

### 4.4 Photo Service wiring (D1-specific)

D1's Photo Service receives both `shared.photos_bucket` (for `grant_read_write` and presigned URL issuance) and `shared.photos_cdn_base_url` (injected as an env var so stored URLs resolve to the CDN, not the raw S3 host).

---

## 5. CloudFormation Outputs

`SharedStack` emits the following `CfnOutput`s — these are the public contract of the stack:

| Output | Value | Consumer |
|--------|-------|----------|
| `UserPoolId` | `self.user_pool.user_pool_id` | Frontend `.env.local`, README live-demo block |
| `UserPoolClientId` | `self.user_pool_client.user_pool_client_id` | Frontend `.env.local` |
| `ApiUrl` | `self.api.url` | Frontend `.env.local`, README |
| `EventBusArn` | `self.event_bus.event_bus_arn` | Diagnostic / AWS-console lookup |
| `PhotosBucketName` | `self.photos_bucket.bucket_name` | Photo Service env (set via CDK reference, not the export) |
| `PhotosCdnBaseUrl` | `https://<distribution_domain>` | Frontend `.env.local`, Photo Service |
| `ActivityStreamArn` | stream ARN **if** Kinesis is enabled | D6 Activity Logger (currently absent — see §5.1) |

Frontend env files are hand-populated from `cdk deploy` output; there is no automated sync.

---

## 6. Known Gotchas / Postmortems

### 6.1 Kinesis disabled on the new AWS account

`self.activity_stream = None` is intentional, not a bug. The new AWS account the project moved to does not yet have Kinesis activated. Any downstream that relies on the stream must tolerate `None` — today, D6 Activity Logger does so by falling back to direct DynamoDB writes. When the quota is granted, uncomment the `kinesis.Stream(...)` block, redeploy Shared, and D6 will re-discover the stream by ARN.

### 6.2 Imported-API stage does not auto-redeploy on route changes

When a domain stack adds or modifies a route on the **imported** REST API, CDK creates/updates the Method/Resource but does **not** automatically trigger a redeployment of the `dev` stage. Symptom: `curl` against the new route returns 403 or `Missing Authentication Token` until the stage is manually redeployed (console → "Deploy API" → `dev`).

This has bitten the team multiple times; see `docs/postmortem/d3-route-revert-2026-04-12.md` for the most recent case. Tracked as **#118**.

### 6.3 Cross-stack deletion/update blocked while exports are in use

Because domain stacks `from_event_bus_name`/`from_rest_api_attributes` off Shared's outputs, CloudFormation records these as exports **in use**. Attempting to update Shared in a way that would change or delete one of those exports fails with `UPDATE_ROLLBACK_COMPLETE` and `Export ... cannot be updated as it is in use by KismetDomainN`.

Mitigation: deploy the affected domain first with `cdk deploy KismetDomainN --exclusively` so the domain stops referencing the old export, then update Shared. In the worst case, destroy/recreate in a specific order per the stack dependency graph.

### 6.4 Photos bucket is public-read (MVP only)

`public_read_access=True` + `BlockPublicAccess` all-off is a demo-grade choice. Production should flip to:
- private bucket
- CloudFront Origin Access Identity / Origin Access Control
- signed URLs for viewing (not just PUT)

This is not tracked as its own issue yet — it's an explicit demo-scope call-out.

### 6.5 `RemovalPolicy.DESTROY` on UserPool and buckets

Every stateful resource in Shared is `DESTROY`. Teardown is clean; accidental teardown is catastrophic. Only acceptable because the demo account holds no real user data.

---

## 7. Open Follow-ups

- **#118** — CDK: imported API Gateway stage auto-redeploy on domain route changes. (see §6.2)
- **Re-enable Kinesis** — uncomment the `kinesis.Stream(...)` block in `shared_stack.py` once the AWS account quota is granted. Remove the `self.activity_stream = None` fallback and drop D6's direct-write path.
- **Lock down photos bucket** — switch to OAC + signed URLs before any non-demo deployment. (see §6.4)
- **Tighten Cognito password policy + CORS origin allow-list** before any non-demo deployment.
- **Frontend env sync** — `UserPoolId`, `UserPoolClientId`, `ApiUrl`, `PhotosCdnBaseUrl` are hand-copied from `cdk deploy` output. A small script that reads stack outputs and writes `.env.local` would remove a manual step.

---

## 8. References

- Top-level overview: [`Design_Doc.md` §4 "Shared Infrastructure"](./Design_Doc.md)
- Event shapes published on `kismet-events`: [`event-schema.json`](./event-schema.json)
- Reusable service construct that consumes Shared: [`kismet_constructs/kismet_service.py`](../../infra/kismet_constructs/kismet_service.py)
- Stack wiring: [`infra/app.py`](../../infra/app.py)
- Domain example of consuming Shared: [`Domain2_Design.md`](./Domain2_Design.md)
- Postmortems touching Shared:
  - [`postmortem/d3-route-revert-2026-04-12.md`](../postmortem/d3-route-revert-2026-04-12.md) — imported-API stage redeploy (#118)
  - [`postmortem/chat-duplicate-messages-2026-04-14.md`](../postmortem/chat-duplicate-messages-2026-04-14.md)
  - [`postmortem/ios-fetch-load-failed-2026-04-14.md`](../postmortem/ios-fetch-load-failed-2026-04-14.md)

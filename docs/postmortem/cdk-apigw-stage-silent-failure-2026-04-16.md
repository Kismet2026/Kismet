# CDK API Gateway Stage Silent-Failure Postmortem — 2026-04-16

## Summary

From 2026-04-14 through 2026-04-16, multiple domain stacks added new API Gateway routes via `cdk deploy`, all of which completed successfully per CloudFormation. But clients calling those routes got `403 Missing Authentication Token` or `404` responses. The root cause: CDK's imported-REST-API pattern **creates the new Resources/Methods but never re-publishes the stage** — so the `dev` stage kept serving an older deployment that didn't know about the new routes. The deploy reported green; production served stale.

Resolved in PR #131 (2026-04-16) by a `synth_stage_redeploy(scope, api=...)` helper that each domain stack now calls at the end of `__init__`.

## Timeline

| Time | Event |
|------|-------|
| 2026-04-14 14:18 PT | Last time the shared `dev` stage was actually re-published (normal behavior before the drift started). |
| 2026-04-15 ~morning | PR #112 merged — adds `POST /photos/{photoId}/confirm` endpoint via D1 stack. `cdk deploy KismetDomain1` reported success. |
| 2026-04-15 through 04-16 | Frontend calls to `/photos/{photoId}/confirm` returned `Missing Authentication Token`. Every photo upload got stuck in `status=pending`, event was never published, D4 image-moderation never ran. Team didn't immediately connect this to the API Gateway stage. |
| 2026-04-16 morning | Users reported bans weren't cleaning up matches (reported in-channel). Investigation into the whole photo-moderation pipeline led to discovering John's uploads were stuck at `pending`. |
| 2026-04-16 15:38 PT | Manual `aws apigateway create-deployment --rest-api-id 879oe39enh --stage-name dev` — routes went live. Issue #118 filed to prevent recurrence. |
| 2026-04-16 20:10 PT | PR #131 merged; all 6 domain stacks redeployed to exercise the new helper. Stage `lastUpdatedDate` now advances on every route change. |

## Root Cause

The shared `apigateway.RestApi` is created once in `SharedStack` with:

```python
self.api = apigateway.RestApi(
    self, "Api",
    rest_api_name="kismet-api",
    deploy_options=apigateway.StageOptions(stage_name="dev"),
    ...
)
```

`deploy_options=...` makes CDK auto-create the initial `AWS::ApiGateway::Deployment` and `AWS::ApiGateway::Stage` **inside SharedStack**, pointing at whatever Methods exist in SharedStack at synth time (just the OPTIONS preflight for `/`).

Each domain stack then imports that API:

```python
imported_api = apigateway.RestApi.from_rest_api_attributes(
    self, "ImportedSharedApi",
    rest_api_id=shared.api.rest_api_id,
    root_resource_id=shared.api.rest_api_root_resource_id,
)
```

New `AWS::ApiGateway::Resource` and `AWS::ApiGateway::Method` resources get created in the domain stack's CloudFormation template targeting the shared API ID. **But there is no corresponding new `AWS::ApiGateway::Deployment`.** The stage keeps pointing at the original SharedStack deployment — which is now stale relative to the actual API definition.

CloudFormation had no way to know this was a problem: every resource it was asked to create got created. `cdk deploy` returned `✅`. Only a manual check of API Gateway's stage `lastUpdatedDate` against recent deploys would have surfaced the drift.

### Why we didn't notice immediately

- The happy path (photo upload without `/confirm`) still worked because the upload endpoint was created pre-2026-04-14 and was in the old deployment.
- D4 image-moderation's own errors were masked by the earlier `Runtime.HandlerNotFound` bug (fixed in #115) — we'd been debugging that layer, not the API Gateway layer.
- Frontend error messages said "Missing Authentication Token" which pointed at Cognito, not at stage state.
- `aws apigateway get-resources` showed the Resource existed. That made the endpoint look wired even though it wasn't actually served.

## Impact

- **Photo moderation loop broken for ~2 days** — no uploads got scanned because `photo.uploaded` events weren't being published (confirm endpoint was 403ing)
- **Auto-ban + ban cascade couldn't be validated end-to-end** until the stage was manually redeployed
- ~2 hours of debugging attributed the symptom to downstream layers (Cognito, D4 handler name, S3 consistency) before the real cause was identified
- Silent failure class: deploys appeared green while serving stale routes. Highest-risk failure mode — no alerting, no error output from CDK.

## Fixes Applied

1. Manual `aws apigateway create-deployment --stage-name dev` to unstick the immediate problem (2026-04-16 15:38 PT).
2. Issue #118 filed documenting the class of bug + two fix options.
3. PR #131 — added `synth_stage_redeploy(scope, api=...)` helper to `infra/kismet_constructs/kismet_service.py`. Each domain stack now calls it once at the end of `__init__`.

**How the fix works:**

- The helper walks `scope`'s construct tree for every `KismetService` (and loose `apigateway.Method` not owned by a KismetService, e.g. D5's scheduler routes).
- Builds a SHA-256 fingerprint from the sorted route specs (e.g. `"GET /discovery,POST /swipe,DELETE /matches/{matchId},..."`).
- Synthesises one `AWS::ApiGateway::Deployment` whose CDK logical ID embeds the first 12 hex chars of the fingerprint. When routes change, the logical ID changes → CFN sees a new resource → creates a fresh Deployment. When routes don't change, the fingerprint is stable → CFN does nothing.
- Sets `StageName=dev` via a `CfnDeployment` property override so the new Deployment attaches to the pre-existing SharedStack stage instead of creating a parallel one.
- Wires `DependsOn` to every Method so CFN doesn't try to snapshot the API before the new methods exist.

All six domain stacks were redeployed in sequence after PR #131 merged; each advanced the stage's `lastUpdatedDate` as expected.

## Action Items

### Immediate (done)
- [x] Fix the helper in `kismet_service.py`
- [x] Wire it into D1–D6 stacks
- [x] Redeploy all six stacks and verify stage `lastUpdatedDate` advances
- [x] Document in `Domain2_Design.md` §7 Known Gotchas and `SharedStack_Design.md`

### Process improvements
- [ ] **Add stage-freshness check to CI/CD**: after any `cdk deploy Kismet*`, query `aws apigateway get-stages` and fail if `lastUpdatedDate` is older than the deploy timestamp. Catches this class of drift if the helper ever breaks.
- [ ] **Smoke-test new routes in CI**: any PR that adds a route under `infra/stacks/*.py` should be accompanied by a curl-based smoke test that hits the new endpoint on the dev deployment and asserts it responds with something other than `Missing Authentication Token` / `404`.
- [ ] **Document the imported-API pattern**: add a short note to `docs/guides/Service_Communication_Guide.md` explaining that imported-API deploys require `synth_stage_redeploy` — so nobody accidentally instantiates an imported API outside of the KismetService helpers and hits this again.

### Lessons
- **Green CFN ≠ working API.** API Gateway is unusual in that "the resource exists" and "the resource is served" are two different facts. For this service family, assume we need both to be verified independently.
- **Silent failures demand smoke tests.** The cost of a 30-second HTTP check against newly-added endpoints is much lower than a 2-day debugging session.
- **Watch for stage-update timestamps during deploys.** A manual spot-check of `aws apigateway get-stages` would have caught this on 2026-04-14.

## Current State (as of 2026-04-16 end of day)

| Component | Status |
|-----------|--------|
| `synth_stage_redeploy` helper | ✅ Merged (#131) |
| D1–D6 stacks deployed with helper | ✅ |
| Stage `lastUpdatedDate` | ✅ `2026-04-16T20:13:05-07:00` (advancing per deploy) |
| #112 confirm endpoint | ✅ Live and serving |
| Photo moderation loop | ✅ End-to-end verified on mobile today |
| CI smoke test for new routes | ⏳ Follow-up |

## Related

- Issue #118 (closed by #131)
- PR #112 (confirm endpoint — the first route this affected)
- PR #114 (report `?status=` filter — also affected)
- PR #115 (unrelated but surfaced during the same debugging session)

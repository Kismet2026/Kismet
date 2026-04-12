# D3 Route Revert Postmortem — 2026-04-12

## Summary

PR #89 accidentally reverted the route conflict fix from PR #86, causing `cdk deploy KismetDomain3` to fail twice. The root cause was a stale branch that carried old route definitions back into main on merge.

## Timeline

| Time | PR | Author | What happened |
|------|-----|--------|---------------|
| 4/10 | #77 | Quanxing | Implemented presence service. Introduced `/messages/{matchId}` and `/presence/{userId}` routes that conflicted with existing path variables. |
| 4/10 | #86 | Quanxing | Fixed route conflicts (closes #83). Changed `/messages/{matchId}` → `/messages/match/{matchId}` and `/presence/{userId}` → `/presence/user/{userId}`. Merged successfully. |
| 4/12 | #89 | Jiaxin | Added auth + participant checks. **Branch was forked before #86 merged**, so `domain3_stack.py` still had old routes. Merge reverted #86's fix. |
| 4/12 | #97 | Qinyuan | Re-applied route fix. Deleted failed CloudFormation stack and redeployed. |

## Root Cause

PR #89's branch (`jiaxin/domain3-security-fixes`) was created from main **before** PR #86 was merged. When #89 was merged, GitHub's merge commit carried the old `domain3_stack.py` (with conflicting routes) back into main, overwriting #86's fix.

Neither the author nor the reviewer noticed because:
- The diff for #89 didn't show the route paths as changed (they matched the old main)
- No CI/CD ran `cdk synth` or `cdk deploy` to catch the regression

Additionally, both PR #88 and #89 sat open with no review or action for an extended period. #89 was already showing merge conflicts on GitHub but was not addressed by the D3 team. During the frontend deployment push, I had to step in personally to rebase #89, resolve conflicts, and merge both PRs to unblock progress.

**This highlights a process gap**: PRs with conflicts should be resolved promptly by their authors, not left for others to clean up under time pressure.

## Impact

- `KismetDomain3` stack failed to deploy twice (entered `ROLLBACK_COMPLETE` state)
- All D3 endpoints (messages, presence, icebreaker, WebSocket) were unavailable
- Frontend CORS + D3 deployment blocked for ~2 hours
- Required manual CloudFormation stack deletion before re-deploy

## Fixes Applied

1. PR #97 — re-applied route changes from #86
2. Deleted `ROLLBACK_COMPLETE` stack from CloudFormation
3. Successfully deployed KismetDomain3
4. Updated frontend API paths to match new routes
5. Redeployed frontend to Vercel

## Action Items

### For D3 Team

- [ ] **Rebase before merge**: Always run `git rebase origin/main` or `git merge origin/main` before merging PRs, especially when multiple PRs touch `domain3_stack.py`
- [ ] **Avoid concurrent edits to stack file**: Coordinate who is editing `domain3_stack.py` at any given time. If multiple PRs need to change it, merge them sequentially and rebase in between
- [ ] **Verify deploy after stack changes**: After merging a PR that modifies any CDK stack, run `cdk deploy` to confirm no regressions

### For Everyone

- [ ] **Add `cdk synth` to CI**: A GitHub Action that runs `cdk synth` on PRs touching `infra/` would catch these conflicts before merge
- [ ] **Protect infra files with CODEOWNERS**: Require review from infra owner for changes to `infra/stacks/*.py` and `infra/kismet_constructs/*.py`

## Current State (as of 2026-04-12)

| Component | Status |
|-----------|--------|
| KismetDomain3 stack | ✅ Deployed |
| WebSocket API | ✅ `wss://0pnx67jcx3.execute-api.us-east-1.amazonaws.com/dev` |
| Message routes | ✅ `/messages/match/{matchId}` |
| Presence routes | ✅ `/presence/user/{userId}` |
| Frontend routes | ✅ Updated and deployed to Vercel |

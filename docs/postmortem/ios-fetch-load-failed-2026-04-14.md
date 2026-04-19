# iOS "Load failed" Postmortem — 2026-04-14

## Summary

All API calls from iOS Safari and Chrome failed with `"Load failed"` — a network-layer error from `fetch()`. The root cause was iOS browsers silently blocking cross-origin requests to AWS API Gateway. Fixed by adding a Next.js API proxy so all browser requests go through the same-origin Vercel server.

## Timeline

| Time | Event |
|------|-------|
| 4/12 | Frontend deployed to Vercel. Signup/verify/login work (tested on desktop). |
| 4/13 | First mobile test on iOS Chrome — signup works, but chat page shows `"Load failed"`. |
| 4/13 | Investigated CORS — preflight returns 204, CORS headers present. Not a CORS issue. |
| 4/13 | Added Gateway Responses with CORS headers for all 4xx/5xx. No improvement on iOS. |
| 4/14 | Added visible debug banner to chat page to diagnose without browser console. |
| 4/14 | Debug shows `ERR(?): Load failed` — token is valid, error is at fetch() network layer. |
| 4/14 | Tested on Safari — same failure. Confirmed iOS-wide, not Chrome-specific. |
| 4/14 | Added Next.js API proxy (`/api/proxy/[...path]`). All requests now same-origin. **Fixed.** |

## Root Cause

iOS browsers (Safari and Chrome, which both use WebKit) silently reject certain cross-origin `fetch()` requests to AWS API Gateway CloudFront distributions. The exact mechanism is unclear but likely related to one or more of:

1. **App Transport Security (ATS)** — iOS enforces strict TLS requirements. API Gateway's CloudFront certificate chain may not meet ATS requirements in all configurations.
2. **DNS/Network layer blocking** — iOS may timeout or block DNS resolution for certain AWS regional endpoints under poor network conditions (the test device showed weak signal).
3. **WebKit fetch() implementation** — WebKit's fetch() throws a generic `TypeError: Load failed` instead of providing specific error details, making diagnosis difficult.

### Key evidence
- `curl` from macOS to the same endpoint worked perfectly (200 with correct CORS headers)
- CORS preflight (OPTIONS) returned 204 with correct headers
- Token was valid and not expired (verified via debug banner)
- Error occurred on **both** Safari and Chrome on iOS (same WebKit engine)
- Desktop Chrome had no issues with the same API calls
- The error was `TypeError: Load failed`, not a CORS error or HTTP status error

## Fix

### Architecture change

**Before (broken on iOS):**
```
iOS Browser  ──fetch()──►  AWS API Gateway (cross-origin)
                           https://ugt4knycyj.execute-api.us-east-1.amazonaws.com/dev
                           ❌ iOS WebKit blocks at network layer
```

**After (working):**
```
iOS Browser  ──fetch()──►  Vercel Server (same-origin)  ──fetch()──►  AWS API Gateway
                           /api/proxy/messages/match/xxx              /messages/match/xxx
                           ✅ Same origin, no restrictions            ✅ Server-to-server
```

### Code changes

1. **New file: `frontend/src/app/api/proxy/[...path]/route.ts`**
   - Catch-all API route that proxies GET/POST/PUT/DELETE requests
   - Forwards Authorization header and request body transparently
   - Returns 502 with error details if the upstream fetch fails

2. **Modified: `frontend/src/lib/api.ts`**
   - `BASE_URL` changed from direct AWS API Gateway URL to `/api/proxy` (browser only)
   - Server-side rendering still uses direct URL (for any future SSR needs)

### Trade-offs

| Benefit | Cost |
|---------|------|
| Eliminates all CORS issues | ~50-100ms added latency per request (extra hop) |
| iOS fully compatible | Vercel serverless function cold starts on first request |
| AWS API URL hidden from client | Slightly more complex architecture |
| No more Gateway Response CORS config needed | Proxy route needs maintenance |

## Lessons Learned

1. **iOS WebKit is not the same as desktop browsers.** Cross-origin fetch() that works perfectly on desktop Chrome/Safari can silently fail on iOS. Always test on real iOS devices early.

2. **"Load failed" is a black box.** iOS WebKit provides no useful error details for network-layer failures. When debugging iOS fetch issues, add visible on-screen debug output since mobile browser consoles are inaccessible.

3. **API proxies are the nuclear option for CORS.** When dealing with mobile browser quirks, routing through a same-origin proxy eliminates an entire class of problems. The latency cost (~50-100ms) is negligible for a dating app.

4. **Don't assume CORS is the problem.** We spent significant time adding CORS headers to API Gateway responses, Gateway Responses for error codes, and redeploying — none of which helped because the issue wasn't CORS. The preflight succeeded; the actual request was blocked at a lower level.

## Prevention

- **Always include a real iOS device in the test matrix** — simulators don't reproduce this
- **Consider API proxy from day one** for mobile-first apps — eliminates an entire class of issues
- **Add a visible error banner** (removable before launch) to surface API errors on mobile during development

## Current State

| Component | Status |
|-----------|--------|
| API proxy | ✅ Deployed at `/api/proxy/[...path]` |
| iOS Safari | ✅ Working |
| iOS Chrome | ✅ Working |
| Desktop browsers | ✅ Working (also uses proxy now) |
| Chat messaging | ✅ Messages persist and load on re-entry |
| WebSocket | ✅ Still connects directly (not proxied — WSS works on iOS) |

# Photo CDN Rollout

## Goal

Provide stable, public-facing photo URLs for Domain 1 without making the shared photos S3 bucket public.

## Current State

- The code changes live in `SharedStack` and `Domain1Stack`.
- The live environment does not use these CloudFront-backed URLs until `KismetShared` and `KismetDomain1` are deployed in that order.

## Problem

`photo-service` builds response URLs and `photo.uploaded` event payloads from `PHOTOS_CDN_BASE_URL`.

When that env var is empty:

- `GET /users/{userId}/photos` returns broken relative paths like `/{s3Key}`
- `photo.uploaded.detail.cdnUrl` is empty
- downstream consumers and the frontend have no canonical public photo URL

## Chosen Fix

Provision a dedicated CloudFront distribution in `SharedStack` for the shared photos bucket and inject its HTTPS base URL into Domain 1 photo-service.

## Architecture

- S3 bucket remains the source of truth for stored photo objects
- CloudFront is the canonical public delivery path
- `photo-service` continues to generate presigned PUT URLs for uploads directly to S3
- `photo-service` uses `PHOTOS_CDN_BASE_URL` only for read URLs and emitted `cdnUrl` values

## Why This Fix

- Keeps the photos bucket private instead of exposing raw S3 objects publicly
- Gives photo-service stable, cacheable URLs
- Matches the existing Domain 1 photo-service API contract
- Avoids cross-domain coupling: this is shared infra plus Domain 1 configuration, not a cross-domain data write

## Scope

### SharedStack

- Add a photos CloudFront distribution with the shared photos bucket as origin
- Output the resulting base URL

### Domain1Stack

- Set `PHOTOS_CDN_BASE_URL` from the shared photos distribution instead of leaving it empty

### Photo Service

- No handler logic change is required
- Existing URL-building logic becomes correct once the env var is populated

## Rollout Steps

1. Deploy `KismetShared`
2. Verify CloudFront distribution creation and output value
3. Deploy `KismetDomain1` so photo-service picks up the new `PHOTOS_CDN_BASE_URL`
4. Upload a photo through `POST /photos/upload`
5. Confirm `GET /users/{userId}/photos` returns `https://<cloudfront-domain>/<s3Key>`
6. Confirm `photo.uploaded` includes a non-empty `cdnUrl`

## Verification

- `cd infra && npx cdk synth --app "python app.py"`
- `cd services/domain-1-identity/photo-service && python -m unittest tests.test_lambda_function`
- Upload a test photo and load the returned CloudFront URL in a browser
- Check that photo-service event payloads use the CloudFront base URL

## Rollback

- Re-deploy the previous `SharedStack` and `Domain1Stack` versions if CloudFront delivery fails
- Expect photo reads to fall back to the old broken behavior unless a temporary alternate `PHOTOS_CDN_BASE_URL` is supplied
- Do not make the photos bucket public as an emergency workaround without an explicit product/security decision

## Non-Goals

- Signed CloudFront URLs
- Image resizing/transformation
- Custom photo CDN domain name
- Cache invalidation workflow for overwrite scenarios

## Follow-Ups

- Add a custom domain if product wants branded photo URLs
- Add image optimization or transformations if payload size becomes a concern
- Consider explicit CloudFront cache policy tuning after real traffic patterns are known

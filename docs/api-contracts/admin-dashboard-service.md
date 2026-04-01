# Admin Dashboard Service — API Contract

**Owner:** Lingyun Xiao
**Domain:** Domain 6 — Analytics & Admin
**AWS Services:** Lambda, DynamoDB, API Gateway
**Status:** 🟡 In Progress

## Description

Internal admin API for viewing app-wide stats and managing user reports. Not exposed to end users.

## Base URL

```
https://<api-gateway-id>.execute-api.<region>.amazonaws.com/prod/admin
```

## Authentication

All endpoints require an admin JWT token in the `Authorization` header.

---

## Endpoints

### GET /admin/stats

Returns high-level app statistics.

**Response:**

```json
{
  "totalUsers": 1024,
  "newUsersToday": 38,
  "totalMatches": 412,
  "matchesToday": 21,
  "messagesToday": 890,
  "swipesToday": 3200
}
```

**Data sources:**

- `totalUsers`, `newUsersToday` — profile-service DynamoDB
- `totalMatches`, `matchesToday` — match-service DynamoDB
- `messagesToday` — message-service DynamoDB
- `swipesToday` — swipe-service DynamoDB

---

### GET /admin/reports

Returns a paginated list of user reports.

**Query Parameters:**

| Param     | Type   | Default   | Description                                          |
| --------- | ------ | --------- | ---------------------------------------------------- |
| `status`  | string | `pending` | Filter by status: `pending`, `resolved`, `dismissed` |
| `limit`   | number | 20        | Number of results per page                           |
| `lastKey` | string | —         | Pagination cursor from previous response             |

**Response:**

```json
{
  "reports": [
    {
      "reportId": "rpt_abc123",
      "reporterId": "user_111",
      "reportedUserId": "user_222",
      "reason": "harassment",
      "description": "Sent inappropriate messages",
      "status": "pending",
      "createdAt": "2026-03-31T10:00:00Z"
    }
  ],
  "lastKey": "rpt_abc123"
}
```

---

### GET /admin/reports/{reportId}

Returns full detail of a single report.

**Response:**

```json
{
  "reportId": "rpt_abc123",
  "reporterId": "user_111",
  "reportedUserId": "user_222",
  "reason": "harassment",
  "description": "Sent inappropriate messages",
  "status": "pending",
  "createdAt": "2026-03-31T10:00:00Z",
  "resolvedAt": null,
  "resolvedBy": null,
  "adminNote": null
}
```

---

### PUT /admin/reports/{reportId}/resolve

Admin resolves a report (dismiss or ban user).

**Request:**

```json
{
  "action": "ban",
  "adminNote": "Confirmed harassment, account suspended"
}
```

| Field       | Type   | Values           |
| ----------- | ------ | ---------------- |
| `action`    | string | `ban`, `dismiss` |
| `adminNote` | string | Optional notes   |

**Response:**

```json
{
  "reportId": "rpt_abc123",
  "status": "resolved",
  "action": "ban",
  "resolvedAt": "2026-03-31T12:00:00Z"
}
```

---

### GET /admin/users/{userId}

Returns a user's profile detail for admin review.

**Response:**

```json
{
  "userId": "user_222",
  "name": "Jane",
  "email": "jane@example.edu",
  "status": "active",
  "createdAt": "2026-03-01T00:00:00Z",
  "reportCount": 3
}
```

---

## DynamoDB Table

**Table name:** `admin-actions`

| Field            | Type   | Description               |
| ---------------- | ------ | ------------------------- |
| `adminId` (PK)   | String | Admin who took the action |
| `timestamp` (SK) | String | ISO timestamp             |
| `action`         | String | `ban`, `dismiss`          |
| `reportId`       | String | Related report            |
| `targetUserId`   | String | User acted upon           |
| `note`           | String | Admin note                |

---

## Dependencies

- **Depends on:** report-service (report data), profile-service (user detail), match-service (match stats), swipe-service (swipe stats), message-service (message stats)
- **Called by:** Admin frontend / Postman
- **Events published:** `admin.user.banned` → EventBridge
- **Events consumed:** None

# Endpoint Templates (Actual Token-Supported)

Set variables first:

```bash
BASE_URL="http://your-server:port"
API_TOKEN="your_token_here"
```

## Header

Preferred:

```http
X-API-Token: ${API_TOKEN}
Content-Type: application/json
```

Alternative:

```http
Authorization: Bearer ${API_TOKEN}
Content-Type: application/json
```

## REST: Download APIs

### Douyin Download

```bash
curl -X POST "${BASE_URL}/api/dyd/download" \
  -H "X-API-Token: ${API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.douyin.com/video/xxx",
    "generate_nfo": true
  }'
```

### Xiaohongshu Download

```bash
curl -X POST "${BASE_URL}/api/xhs/download" \
  -H "X-API-Token: ${API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.xiaohongshu.com/explore/xxx",
    "generate_nfo": true
  }'
```

### YouTube / Bilibili Download

```bash
curl -X POST "${BASE_URL}/api/ytd/download" \
  -H "X-API-Token: ${API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=xxx"
  }'
```

```bash
curl -X POST "${BASE_URL}/api/ytd/download" \
  -H "X-API-Token: ${API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.bilibili.com/video/xxx"
  }'
```

## REST: Live APIs (`/api/live/*`)

Confirmed token-supported endpoints:

- `GET /api/live/subscriptions`
- `POST /api/live/subscriptions`
- `GET /api/live/status`
- `POST /api/live/status/refresh/{sub_id}`
- `POST /api/live/record/start/{sub_id}`
- `POST /api/live/record/stop/{sub_id}`
- `GET /api/live/record/status/{sub_id}`

Example:

```bash
curl -X GET "${BASE_URL}/api/live/status" \
  -H "X-API-Token: ${API_TOKEN}"
```

```bash
curl -X POST "${BASE_URL}/api/live/record/start/<SUB_ID>" \
  -H "X-API-Token: ${API_TOKEN}"
```

## WebSocket (`/api/ws/subscribe/*`)

WebSocket auth accepts:
- query token: `?token=<API_TOKEN>` (or JWT)
- header `Authorization: Bearer <API_TOKEN>`
- header `x-api-token: <API_TOKEN>`

Example:

```text
ws://<host>/api/ws/subscribe/metrics/progress?token=<API_TOKEN>
```

Common channels:
- `/api/ws/subscribe/metrics/progress`
- `/api/ws/subscribe/downloads/progress`
- `/api/ws/subscribe/announcements/progress`
- `/api/ws/subscribe/live_status`
- `/api/ws/subscribe/transcode`

## Not Supported By API Token

- `/api/auth/tokens*` (create/list/delete/regenerate/update token) uses JWT user auth, not API Token.
- Endpoints using `get_current_user` (JWT-only) do not accept API Token.

## Quick Troubleshooting

1. `401 无效的 API Token`
- Token value typo.
- Token not found in `api_tokens`.
- `is_active` is not `"true"`.
- `expires_at` already expired.

2. `400 小红书链接请使用 /api/xhs/download`
- URL platform and endpoint do not match.

3. WebSocket `1008 Unauthorized`
- Missing token in query/header.
- Token expired or inactive.
- Browser still holds old token after service restart.

4. Endpoint accepts token but token management fails
- `/api/auth/tokens*` endpoints require JWT user login; API Token is for business APIs.

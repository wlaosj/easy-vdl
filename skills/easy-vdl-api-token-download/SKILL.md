---
name: easy-vdl-api-token-download
description: Call Easy-VDL APIs with a pre-created API Token. Use when the user needs token-based invocation for download APIs, live APIs, websocket auth headers, endpoint selection, or token validity troubleshooting.
---

# Easy-VDL API Token Skill

Use the existing API Token directly in request headers.

## Follow This Workflow

1. Ask user to provide custom runtime values first:
- `base_url` (for example: `http://127.0.0.1:8080` or `https://api.example.com`)
- `api_token` (user-owned existing token)

2. Confirm target endpoint by use case:
- Douyin: `/api/dyd/download`
- Xiaohongshu: `/api/xhs/download`
- YouTube/Bilibili: `/api/ytd/download`
- Live subscription/status/record control: `/api/live/*`
- WebSocket channels: `/api/ws/subscribe/*` (token in header/query)

3. Send token with one of these headers:
- `X-API-Token: <token>` (preferred)
- `Authorization: Bearer <token>`

4. Use JSON body with at least `url`.

5. If request returns `401`:
- Verify token exists in `api_tokens`.
- Verify `is_active` is `"true"`.
- Verify `expires_at` is empty or in the future.

6. If request returns platform mismatch `400`, switch to the correct download endpoint.

7. Important boundary:
- `/api/auth/tokens*` is token-management API, it requires JWT user login, not API Token.

## Read Reference

For ready-to-run command templates and troubleshooting checklist, read:
- `references/endpoints.md`

# API contract: Milestone A

The dashboard and every client talk to the backend through this contract. Message shape: [`packages/protocol/ccmp.schema.json`](../../packages/protocol/ccmp.schema.json) (CCMP v1).

All paths are under `/api`. JSON in and out. Errors: `{"error": {"code": "snake_case", "message": "Human readable"}}` with a matching HTTP status.

## Authentication (single owner, Milestone A)

- The owner password comes from `OWNER_PASSWORD` in the backend environment (minimum 12 characters). The backend refuses to start without it.
- Session: an opaque random token in the `cc_session` cookie (`HttpOnly`, `SameSite=Strict`, `Path=/`, `Secure` when served over HTTPS). Stored server-side as a SHA-256 hash. Expires after 12 hours.
- **CSRF:** every non-GET request must send the header `X-CC-CSRF: 1`. The API does not enable CORS, so a cross-site page cannot add that header.
- **WebSocket:** authenticated by the same cookie; the `Origin` header must be in `ALLOWED_ORIGINS`.
- Login is rate limited (5 failed attempts per 5 minutes per client IP). `X-Forwarded-For` is ignored.
- Request bodies over 128 KB are rejected with `413 payload_too_large` before they are parsed.
- The `Host` header must be `localhost`, `127.0.0.1`, or a host from `ALLOWED_ORIGINS` (otherwise `400`).
- An open WebSocket is re-authorized on every wake-up: logging out closes it immediately, and an expired session closes it within one heartbeat (`4401`).

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| POST | `/api/auth/login` | `{"password": "..."}` | `200 {"principal": Principal}` + cookie; `401 invalid_credentials`; `429 rate_limited` |
| POST | `/api/auth/logout` | none | `204` |
| GET | `/api/auth/me` | none | `200 Principal`; `401 unauthenticated` |

`Principal`: `{"id": "usr_...", "kind": "owner", "display_name": "Noel"}`

## Rooms

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| GET | `/api/rooms` | none | `200 Room[]` ordered by name |
| POST | `/api/rooms` | `{"name": "Design review"}` (1 to 80 chars, unique) | `201 Room`; `409 room_exists`; `422 validation_error` |
| GET | `/api/rooms/{room_id}` | none | `200 RoomDetail`; `404 room_not_found` |

`Room`: `{"id": "room_...", "name": "General", "created_at": "...", "member_count": 1, "last_seq": 42}` (`last_seq` is `0` for an empty room)

`RoomDetail`: `Room` plus `"members": Principal[]`

A default room named `General` exists on first start; the owner is a member of every room.

## Messages

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| GET | `/api/rooms/{room_id}/messages?after_seq=0&limit=100` (`after_seq` 0 to 2^63-1) | none | `200 {"items": Message[], "has_more": bool, "next_after_seq": int}` ascending by `seq`; `limit` 1 to 200 |
| POST | `/api/rooms/{room_id}/messages` | `{"kind": "chat", "body": {"text": "..."}, "reply_to": null, "mentions": [], "idempotency_key": "client-uuid"}` | `201 Message` (new) or `200 Message` (same `idempotency_key` from the same sender: returns the original, never a duplicate) |

- `text` 1 to 32,000 characters after trimming. `idempotency_key` 8 to 100 characters, required.
- `mentions`: up to 50 principal ids (`usr_`, `agt_`, `ext_` or `sys_` plus 32 hex characters).
- Reusing an `idempotency_key` in a different room returns `409 idempotency_conflict`.
- Only `kind: "chat"` may be posted by the dashboard in Milestone A.

`Message` is a CCMP v1 envelope exactly as in the schema. `seq` is gap-free and increasing **within each room** (1, 2, 3, ...), assigned under a per-room lock so messages always commit in `seq` order; `after_seq` is therefore always per room.

## Real-time: WebSocket

`GET /api/ws/rooms/{room_id}?after_seq=N` (upgrade)

Server to client frames (JSON text):

| Frame | Meaning |
| --- | --- |
| `{"type": "message", "message": Message}` | A message with `seq > N`. On connect the server first replays everything after `N` in order, then streams new messages live. |
| `{"type": "ready", "last_seq": 57}` | Replay finished; everything up to `last_seq` has been sent. |
| `{"type": "ping", "ts": "..."}` | Heartbeat every 15 seconds. |

Client to server frames: `{"type": "pong"}` (optional). Messages are never sent over the socket; clients POST them.

Close codes: `4400` invalid `after_seq`, `4401` unauthenticated or session ended, `4403` origin not allowed, `4404` room not found. Clients must not auto-reconnect after `4401`, `4403` or `4404`.

**Client reconnect rule:** keep the highest `seq` seen; on close or 30 seconds without any frame, reconnect with exponential backoff (1 s doubling to 30 s, with jitter) using `after_seq=<highest seq>`. Deduplicate by `id`, since a message can arrive on both the socket and a POST response.

## Health

`GET /api/health` (no auth): `200 {"status": "ok", "database": "ok"}` or `503`.

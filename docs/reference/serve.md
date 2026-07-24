# Serve (HTTP + JSON)

A thin, **read-only** HTTP server that exposes a store's data to out-of-process
consumers — a memory browser, another frontend — over plain HTTP + JSON. Stdlib
only (no dependency, no framework), and it ships with the package like the
[CLI](/reference/cli).

The server is a **shell over the [Core API](/reference/api)**: every endpoint
maps 1:1 to an API method and does nothing but route, convert params, and
JSON-encode. A serve response can never diverge from the equivalent Python call
(ADR-0004). The host process does not use serve — it imports the API directly;
serve is for *other* processes.

## Launch

```bash
wikimem -s memory/ serve                               # http://127.0.0.1:8787
wikimem -s memory/ serve --port 9000
wikimem -s memory/ serve --cors http://localhost:5173  # allow a cross-origin frontend
```

Or in-process:

```python
from wikimem import MemoryStore, serve

serve(MemoryStore("memory/"), port=8787, cors="http://localhost:5173")
```

## Endpoints

All are `GET`, return JSON, and answer `404` on an unknown path / `400` on a bad
parameter (`{"error": "..."}`).

| endpoint | API call | returns |
|---|---|---|
| `/version` | — | `{"name": "wikimem", "version": "..."}` |
| `/diary/dates` | `diary.dates()` | `["2026-07-20", ...]` |
| `/diary/day/{date}` | `diary.day(date)` | the day's entries, chronological |

A diary entry is the [`DiaryEntry`](/reference/api#memoryitem-diaryentry-wikilink)
fields as JSON:

```json
{
  "date": "2026-07-20",
  "time": "14:30",
  "content": "他说换了工作，语气很兴奋。[[work:current-job]]",
  "owner": "user:xnne",
  "source_conv": "conv_1",
  "ts": "2026-07-20T06:30:00+00:00"
}
```

::: info Planned
`/diary/window?start=&end=` (inclusive range read) follows once its `window()`
method lands, then the wiki / retrieval endpoints (`/categories`, `/items`,
`/retrieve`, `/graph`, `/journal`) — see the serve tracking issue. Write
endpoints are not exposed by design.
:::

## Security

Read this before changing the bind address.

- **Binds `127.0.0.1`, no authentication.** It is for *local* consumers only. Do
  not expose it publicly (`--host 0.0.0.0`) without putting your own auth/proxy
  in front.
- **CORS is off by default.** A page from another origin cannot read your memory
  via a localhost `fetch`. Pass `--cors <origin>` with your frontend's exact
  origin to opt in — only trust origins you control.
- **Read-only.** No endpoint mutates the store; the only writers are the Python
  API and the host's memorize path.

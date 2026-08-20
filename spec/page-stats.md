# page_stats contract

One capability, implemented three times. Every implementation in this repository
answers to this document; the differences between them are contract differences,
not behaviour differences.

## Capability

Fetch an `http`/`https` URL and report the page title and the number of words in
the body.

## Input

| Field | Type | Required | Default | Constraint |
| --- | --- | --- | --- | --- |
| `url` | string | yes | none | Must parse as an absolute URL with scheme `http` or `https` |
| `timeout_seconds` | integer | no | `10` | `1 <= n <= 60` |

## Configuration

Configuration is set by whoever installs the tool, not by the model.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `user_agent` | string | `dialects-page-stats/1.0` | Sent as the `User-Agent` request header |
| `max_bytes` | integer | `2000000` | Stop reading the response body after this many bytes |

## Success

```json
{
  "ok": true,
  "url": "http://127.0.0.1:8080/article",
  "final_url": "http://127.0.0.1:8080/article",
  "status": 200,
  "content_type": "text/html; charset=utf-8",
  "title": "Tide Tables & Other Regularities",
  "word_count": 37,
  "truncated": false
}
```

`title` is `null` when the document has no `<title>` element.
`truncated` is `true` when the body hit `max_bytes` before the response ended.

## Failure

```json
{
  "ok": false,
  "error_code": "timeout",
  "message": "No response within 1s."
}
```

| `error_code` | Cause |
| --- | --- |
| `invalid_url` | Not an absolute `http`/`https` URL |
| `invalid_parameter` | `timeout_seconds` is not a whole number in `1..60` |
| `timeout` | No response within `timeout_seconds` |
| `unreachable` | DNS failure, connection refused, TLS failure, socket reset |
| `http_error` | Response status outside 200-299; `status` is included |
| `unsupported_content_type` | `Content-Type` is not `text/html` or `application/xhtml+xml`; `content_type` is included |

How that failure reaches the agent is where the three ecosystems diverge. See the
root README.

## Parsing

Fixed algorithm, so the three implementations produce identical numbers on
identical bytes.

1. Decode the body as UTF-8, replacing undecodable bytes.
2. Take the first `<title>` element's text as the title candidate.
3. Delete `<script>`, `<style>`, and `<title>` elements including their contents.
   A block left unterminated by truncation is deleted to end of input.
4. Delete every remaining `<...>` tag.
5. Decode `&amp;`, `&lt;`, `&gt;`, `&quot;`, `&#39;`, `&nbsp;`, and numeric
   references `&#NNN;` / `&#xHH;`. No other named entities.
6. Split on Unicode whitespace. `word_count` is the number of non-empty tokens.

Step 5 is deliberately a short fixed list rather than each language's stdlib
entity table, so that Python and TypeScript cannot drift.

The title goes through steps 5 and 6's whitespace collapsing, then is trimmed. An
empty result becomes `null`.

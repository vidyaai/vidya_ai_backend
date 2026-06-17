# Embedding Vidya AI in Your Site

Vidya AI's chat and course/assignment UI can be embedded directly into your
site via an `<iframe>`. Two modes are supported:

- **Authenticated mode** — your users are logged into your site; you mint a
  short-lived signed token so Vidya knows who they are.
- **Demo mode** — no auth, for public/marketing pages (e.g. a Google Sites
  page). Everyone shares a single demo account.

## 1. Authenticated mode

### 1.1 Get your credentials

Vidya AI provisions you a `slug` (tenant identifier) and an `embed_secret`.
Keep the secret server-side only — never expose it to the browser.

### 1.2 Mint a handoff token (your backend)

Sign a short-lived (≤5 minute) HS256 JWT with your `embed_secret`:

**Node**
```js
import jwt from "jsonwebtoken";

function mintVidyaToken(user, course) {
  return jwt.sign(
    {
      sub: user.id,           // your internal user id - becomes part of the Vidya UID
      name: user.fullName,
      email: user.email,
      role: "student",        // or "professor" - omit to use your account's default
      course: course?.id,     // optional: pre-select a course in /embed/assignments
      video: course?.videoId, // optional: pre-select a video in /embed/chat
    },
    process.env.VIDYA_EMBED_SECRET,
    {
      algorithm: "HS256",
      issuer: "<your-slug>",
      audience: "vidyaai-embed",
      expiresIn: "5m",
    }
  );
}
```

**Python**
```python
import jwt
from datetime import datetime, timedelta, timezone

def mint_vidya_token(user, course=None):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "name": user.full_name,
        "email": user.email,
        "role": "student",
        "course": course.id if course else None,
        "iss": "<your-slug>",
        "aud": "vidyaai-embed",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return jwt.encode(payload, VIDYA_EMBED_SECRET, algorithm="HS256")
```

### 1.3 Embed the iframe (your page)

```html
<iframe
  id="vidya-frame"
  src="https://vidyaai.co/embed/chat?token=GENERATED_JWT"
  style="width: 100%; height: 800px; border: 0; display: block;"
  allow="microphone; camera; clipboard-write"
  loading="lazy"
></iframe>

<script>
  window.addEventListener("message", (e) => {
    if (e.origin !== "https://vidyaai.co") return;
    if (e.data && e.data.type === "vidya-resize") {
      const f = document.getElementById("vidya-frame");
      if (f) f.style.height = e.data.height + "px";
    }
  });
</script>
```

For course/assignment management, use `/embed/assignments` instead of
`/embed/chat`.

## 2. Demo mode (no auth)

For public pages (e.g. Google Sites, which doesn't allow custom JS), use a
fixed-height iframe pointing at the demo session:

```html
<iframe
  src="https://vidyaai.co/embed/chat?demo=true"
  width="100%"
  height="800"
  frameborder="0"
  allow="microphone; camera; clipboard-write">
</iframe>
```

Demo sessions are rate-limited and share a single demo account/course - do
not use this for real user data.

## 3. Notes

- Tokens are valid for at most 5 minutes and single-use in the sense that a
  fresh token is exchanged for a Vidya session on every page load - mint a
  new one per iframe load, don't cache it.
- Each `sub` value gets its own isolated Vidya account scoped to your tenant
  (`embed_<your-slug>_<sub>`), so different `sub`s never see each other's
  data.
- If your site's CSP has `frame-src 'self'`, add:
  ```
  Content-Security-Policy: frame-src https://vidyaai.co;
  ```
- Embed pages render without Vidya's top navigation and have no links back to
  vidyaai.co - they're meant to live entirely inside your UI.

# Embed Feature — Local Dev Testing Guide

Internal guide for testing the `/embed/chat` and `/embed/assignments` routes
end-to-end on your machine. For the customer-facing integration guide, see
[embed-integration.md](./embed-integration.md).

This environment has already been set up with the values below — skip to
[step 5](#5-browser-test-embedchat-direct) if your servers are already
running.

## 0. One-time setup (already done in this checkout)

1. Fixed `alembic.ini` (`Vidya%40123` → `Vidya%%40123` on the `sqlalchemy.url`
   line — `%` needs escaping for configparser).
2. Rebased the new `embed_clients` migration
   (`f564fb40bec5_17_migration_add_embed_clients.py`) onto the current head
   and ran:
   ```bash
   cd vidya_ai_backend
   vidyaai_env/bin/alembic upgrade head
   ```
3. Provisioned a test tenant:
   ```bash
   cd vidya_ai_backend/src
   python -m scripts.provision_embed_client xyz_learn "XYZ Learn"
   ```
   ```
   slug=xyz_learn
   embed_secret=KDlKn4iinax__79-R03gRtYJsOZtfOFxiiiUwD2aM3g
   ```
   This secret is for **local testing only**. Re-provision with a fresh
   secret before sharing this with a real customer.

If you're starting from a clean DB / checkout, repeat steps 1–3 above first.

## 1. Mint a test JWT

Embed handoff tokens are HS256, signed with the tenant's `embed_secret`. Two
separate checks gate token age on the backend:

- `exp` (standard JWT expiry) — set this to whatever you like.
- `iat` staleness — `verify_embed_token` also rejects tokens whose `iat` is
  more than `EMBED_MAX_TOKEN_AGE_SECONDS` (default **300s / 5 min**) old,
  **regardless of `exp`**. This is a replay/staleness guard, not the same as
  expiry.

For local testing, `vidya_ai_backend/.env` sets
`EMBED_MAX_TOKEN_AGE_SECONDS=3600` (1 hour) so tokens don't go stale mid-test.
**Restart `uvicorn` after pulling this change** for it to take effect. Do
**not** raise this in production — it's a local-only convenience.

```bash
cd vidya_ai_backend/src
python - <<'EOF'
import jwt, datetime
now = datetime.datetime.now(datetime.timezone.utc)
token = jwt.encode({
    "sub": "student-1",
    "name": "Test Student",
    "email": "student1@xyzlearn.com",
    "iss": "xyz_learn",
    "aud": "vidyaai-embed",
    "iat": now,
    "exp": now + datetime.timedelta(minutes=50),
}, "KDlKn4iinax__79-R03gRtYJsOZtfOFxiiiUwD2aM3g", algorithm="HS256")
print(token)
EOF
```

Copy the printed token — you'll paste it into URLs/`test.html` below. With
the local `.env` override, this token is valid for ~50 minutes.

## 2. Start the backend

```bash
cd vidya_ai_backend/src
uvicorn main:app --reload --port 8000
```

## 3. Start the frontend

```bash
cd vidya_ai_frontend
npm run dev
```

Next.js will use port 3000 (or the next free port — check the terminal
output). The examples below assume **3000**.

## 4. Sanity check: session exchange via curl

```bash
curl -X POST http://localhost:8000/api/embed/session \
  -H "Content-Type: application/json" \
  -d '{"token":"<JWT from step 1>"}'
```

Expect a JSON response with `firebase_token`, `course_id`, `video_id`,
`user_type`. If you get `401 Unknown tenant`, re-check the provisioning step;
if `401 Token expired`, mint a new JWT (step 1).

Demo mode (no token needed):

```bash
curl http://localhost:8000/api/embed/demo-session
```

## 5. Browser test: `/embed/chat` (direct)

Open:

```
http://localhost:3000/embed/chat?token=<JWT from step 1>&v=dQw4w9WgXcQ
```

Expected:
- Briefly shows a spinner, then signs in silently (no Vidya login screen).
- Renders the chat UI for the YouTube video `dQw4w9WgXcQ`, with **no**
  top nav bar, no "Home"/"My Gallery" buttons, no back arrow.

If you see a red error message instead, the token likely expired — go back
to step 1.

## 6. Browser test: `/embed/assignments` (direct)

```
http://localhost:3000/embed/assignments?token=<JWT from step 1>
```

Expected: chrome-less assignments view for the `student-1` user (student
view, since no `role` claim was set — falls back to `default_user_type`
`student`). No course is preloaded since the test JWT has no `course` claim.

## 7. Demo mode test (no auth)

```
http://localhost:3000/embed/assignments?demo=true
```

Expected: signs in as the shared demo user automatically, no token needed.
Hit it a few times — after 10 requests/min from the same IP you should get a
`429 Too many demo session requests` from `/api/embed/demo-session`.

## 8. `test.html` — real iframe test

A test harness is already created at `vidya_ai_frontend/test.html` with three
iframes (authenticated chat, authenticated assignments, demo assignments) and
a `vidya-resize` postMessage listener that auto-resizes each iframe.

1. Edit `test.html` and replace both `TOKEN_PLACEHOLDER` occurrences with a
   fresh JWT from step 1 (mint right before loading the page — it expires in
   5 minutes).
2. Serve it on a different port than the frontend (already allow-listed in
   backend CORS):
   ```bash
   cd vidya_ai_frontend
   python3 -m http.server 3001
   ```
3. Open `http://localhost:3001/test.html`.

Expected: all three iframes load chrome-less Vidya UI and resize themselves
to fit their content (watch the chat iframe shrink/grow as the page loads).

## 9. Embedding on Google Sites

Target page: `https://sites.google.com/view/pingakshya-goswami/`

Google Sites is served over **HTTPS**, while your local backend/frontend are
plain **HTTP**. Browsers block HTTPS pages from framing HTTP content
("mixed content"), so a direct `http://localhost:3000/embed/...` iframe will
likely render blank with a console error like:

```
Mixed Content: The page at 'https://sites.google.com/...' was loaded over
HTTPS, but requested an insecure frame 'http://localhost:3000/...'.
```

You have two options:

### Option A — quick visual check (your browser only)

1. Open `https://sites.google.com/view/pingakshya-goswami/` in Chrome.
2. Click the site-info icon (left of the URL) → **Site settings**.
3. Set **Insecure content** to **Allow**, then reload the page.
4. In the Google Sites editor, insert an **Embed** block → **Embed code**,
   and paste:
   ```html
   <iframe
     src="http://localhost:3000/embed/chat?token=<fresh JWT>&v=dQw4w9WgXcQ"
     width="100%" height="800" style="border:0"
     allow="microphone; camera; clipboard-write">
   </iframe>
   ```
5. Publish/preview. This only works in *your* browser with the flag set —
   not representative of what real visitors would see, but good enough to
   confirm the iframe renders correctly inside the Google Sites layout.

### Option B — full HTTPS test via a tunnel (recommended for a real check)

Use a tunnel so both frontend and backend are reachable over HTTPS, just like
production:

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000   # → backend HTTPS URL
cloudflared tunnel --url http://localhost:3000   # → frontend HTTPS URL
```

Then:

1. Add the backend tunnel URL to `allow_origins` in
   `vidya_ai_backend/src/main.py`'s `CORSMiddleware` config (temporary, for
   testing — revert afterwards).
2. Set `NEXT_PUBLIC_API_BASE_URL=<backend tunnel URL>` in `.env.local` and
   restart `npm run dev` (Next.js inlines `NEXT_PUBLIC_*` vars at startup).
3. Mint a fresh JWT (step 1) — `embed_secret`/`iss`/`aud` are unchanged.
4. In Google Sites, insert an **Embed** block → **Embed code** with:
   ```html
   <iframe
     src="<frontend tunnel URL>/embed/chat?token=<fresh JWT>&v=dQw4w9WgXcQ"
     width="100%" height="800" style="border:0"
     allow="microphone; camera; clipboard-write">
   </iframe>
   ```
5. Publish/preview — this is now a real HTTPS-to-HTTPS embed and behaves the
   same as it would for a real customer.

Revert the CORS and `.env.local` changes from Option B once you're done
testing.

## 10. Cross-tenant isolation check

Provision a second tenant and confirm it gets a completely separate Vidya
account:

```bash
cd vidya_ai_backend/src
python -m scripts.provision_embed_client acme_school "Acme School"
```

Mint a JWT with `"iss": "acme_school"`, `"sub": "student-1"` (same `sub` as
before, different tenant), signed with `acme_school`'s `embed_secret`. Open
it in `/embed/chat?token=...`.

Expected: this signs in as Firebase UID `embed_acme_school_student-1` — a
**different** account from `embed_xyz_learn_student-1`, even though `sub` is
identical, because the UID is namespaced per tenant. Any courses/videos/chat
history created under one tenant should not appear under the other.

# Keyroom — Xiaomi device keys

Made by **Edd White**. Public source: [K1ngSk1n/keyroom](https://github.com/K1ngSk1n/keyroom).

A public-facing web adaptation of Piotr Machowski's Xiaomi Cloud Tokens
Extractor. QR sign-in only: choose a Xiaomi Home region, scan with Xiaomi
Home, approve sign-in, then search devices and reveal/copy tokens or BLE
bind keys. Export results as JSON or end the session to clear them.

## Run locally

Python 3.15 (the tested runtime):

```sh
git clone https://github.com/K1ngSk1n/keyroom.git
cd keyroom
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
python3 tools/package.py
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1 --no-access-log --no-proxy-headers
```

Open http://localhost:8080 (the default allowed origin). Using 127.0.0.1
in the browser instead requires PUBLIC_ORIGIN=http://127.0.0.1:8080.

Opening `app/static/index.html` directly also displays a styled layout
preview, including in Safari. The preview disables sign-in because the
Xiaomi login flow requires the running backend above.

## Deploy on your website

This app needs a Python backend with outbound HTTPS access to Xiaomi.
There is no browser extension in this edition. Unlike the earlier local
extension prototype, your VPS temporarily processes visitor sessions and
keys, with the disclosures and cleanup described below.
Use a dedicated subdomain such as keys.your-domain.example. Static-only
hosting and the Sites plugin's Worker runtime do not run this Python app;
deploy the Docker package on a VPS/Unraid or another container host.

1. Copy the project to the server. Create `.env` from `.env.example` and
   set PUBLIC_ORIGIN to the exact public HTTPS origin, with no path or
   trailing slash.
2. Use the supplied packaged build (with generated source/build files),
   or run `python3 tools/package.py` from a clean Git checkout first.
   Then run `docker compose up -d --build`.
3. Route the dedicated HTTPS subdomain to `127.0.0.1:8080` through your
   existing reverse proxy. Preserve the public Host header. Keep the
   container's port bound to loopback.
4. Add a normal link from your website to the tool's subdomain. This app
   deliberately blocks iframe embedding and cross-origin API access.

Example Caddy configuration when Caddy runs on the host:

```caddyfile
keys.your-domain.example {
    request_body {
        max_size 2KB
    }
    reverse_proxy 127.0.0.1:8080
}
```

For a containerized proxy, use a private Docker network instead of
loopback, remove published ports and proxy to `keyroom:8080`. Configure
the public Host header consistently. Do not expose the app over plain
HTTP on the Internet. TLS termination and DNS belong to your hosting
configuration; the application is not a TLS server.

Do not enable proxy request/response-body logging, replay, analytics,
CDN caching, or session recording on this subdomain. Standard application
access logging is disabled. Infrastructure logs can still record IPs and
request metadata; document your operator's privacy practices accurately.
Disable swap/core dumps if you require secrets never to reach disk at the
host level. The app's no-database policy is not a guarantee about host
memory, swap, crash dumps, or browser-managed memory.

Run **one worker / one replica**: sessions are process-local. The default
app limit is eight active Xiaomi tasks, 64 retained sessions, and ten QR
starts per source address per 15 minutes. Behind a reverse proxy, the app
sees the proxy's address because forwarded headers are deliberately
untrusted. Add real per-client rate limiting at the edge. The shared app
limit remains a global backstop; do not blindly trust X-Forwarded-For.

## Data handling

- Separate, random HttpOnly session cookies, SameSite=Strict and Secure
  when PUBLIC_ORIGIN is HTTPS.
- Consent before starting a Xiaomi session. The operator temporarily
  processes the Xiaomi session and returned keys, even with QR login.
- Xiaomi credentials/cookies and results are held in process memory;
  nothing is written to an application database or credential file.
- Cloud cookies are discarded when retrieval finishes. Result sessions
  expire after ten minutes from creation (swept every five seconds).
- Ending a session clears result references immediately. In-flight
  requests can take up to their timeout to finish; cancelled workers
  cannot repopulate results. Clearing Python references is not guaranteed
  cryptographic memory zeroization.
- Closing a browser tab alone does not immediately delete server state;
  expiry still applies. Refreshing does not automatically redisplay old
  results. Use “End session & clear results” before leaving shared devices.
- Downloads and clipboard copies remain under the visitor's control and
  may persist after the session ends. Exports contain unmasked secrets.
- No user-supplied URLs are fetched. Xiaomi-provided HTTPS endpoints and
  every redirect are restricted to account.xiaomi.com (including regional
  subdomains) and api.io.mi.com (including regional/STS subdomains).
- Origin/Host checks, cross-site API rejection, no-store responses, a
  restrictive Content Security Policy, and no third-party page assets.
- QR sign-in authorizes this server's Xiaomi session. Ending the web
  session clears local state; it does not claim to revoke Xiaomi's
  server-side authorization. Visitors can manage sessions in Xiaomi.

## Limits and launch validation

This is an unofficial Xiaomi API, based on upstream behavior. Xiaomi can
change login, add verification, reject data-center IPs or rate-limit calls.
The app supports QR login, not password/CAPTCHA/2FA fallback. If Xiaomi
requests an unsupported challenge, it reports failure rather than
attempting to bypass it. Device lists currently use the upstream first
200 devices per home and cap combined results at 1,000; unusually large
accounts can be incomplete. Each region that fails is reported in the UI.
Shared homes are included when returned by Xiaomi.

Validation performed on 2026-11-26:

- Automated API tests for session isolation, consent, expiry, deletion,
  cookie attributes, CSRF/Host checks, rate limits, cancellation races,
  QR visibility, error redaction, URL restrictions and crypto roundtrip.
- Python and JavaScript syntax checks.
- Live QR creation against Xiaomi succeeded without signing into an account.
- Desktop browser rendering checked locally.

Still required before public launch: an account owner's complete QR
approval/device-retrieval test on the final hosting IP, confirmation of
the real domain/TLS/proxy setup, and Docker build verification on that
host. No user's real device credentials are included in this project.

## Tests

```sh
.venv/bin/pip install pytest httpx
.venv/bin/python -m pytest -q
node --check app/static/app.js
```

Upstream attribution and MIT terms: UPSTREAM.md and THIRD_PARTY_LICENSE.

## Traceable source

See TRACEABILITY.md. `/source` exposes this build's readable source and
checksums, while `/api/build` identifies its version and Git revision.
Dependencies are pinned in requirements.lock. A local Git history bundle
is supplied alongside the release. Source downloads intentionally expose
only tracked application files, never configuration secrets or sessions.

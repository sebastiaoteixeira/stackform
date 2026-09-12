# Cookie (BFF) session delivery

`session.delivery` selects how the app session token reaches the client. It
defaults to `token-url`, which returns the token in the login response body.
Setting it to `cookie` switches the app
into a Backend-for-Frontend (BFF) posture: the session never touches
JavaScript-readable storage.

```yaml
session:
  delivery: cookie   # token-url (default) | cookie
```

## What cookie delivery changes

On login the server sets a `Secure; HttpOnly; SameSite=Lax` cookie named
`session` carrying the app JWT, and a second, JavaScript-readable
`csrf_token` cookie. The login body no longer contains `token`; it returns the
safe user record plus the freshly minted `csrf_token`.

Principal resolution reads the `session` cookie when no `Authorization` header
is present, so cookie and bearer clients are both accepted (the header wins).

## CSRF (double-submit)

CSRF protection is wired automatically - it is not a user knob. A middleware
enforces the double-submit pattern: for any unsafe method (`POST`, `PUT`,
`PATCH`, `DELETE`) issued by a request that carries a `session` or
`refresh_token` cookie, the
`x-csrf-token` header must equal the `csrf_token` cookie. Requests without a
session cookie (login, register) are exempt so the flow can bootstrap. A
mismatch or missing header is rejected with `403 CSRF token missing or invalid`.

The client reads `csrf_token` from its cookie (it is not `HttpOnly`) and echoes
it back in the `x-csrf-token` header on every mutating call.

## Refresh under cookie delivery

When `session.refresh` is also enabled, the refresh token is delivered in a
third `HttpOnly` cookie (`refresh_token`). The `/refresh` route reads it from
the cookie rather than the request body, rotates it, and re-sets all cookies.
Rotation and reuse detection are unchanged.

The refresh cookie remains CSRF-protected when the short-lived session cookie
has expired. A client must therefore retain and submit the current CSRF token
while refreshing the session.

## Provider login and logout

Password and OIDC login flows use the same cookie contract in both runtime and
generated FastAPI backends. Generated FastAPI SAML callbacks use that contract
as well. OIDC's one-time-code exchange sets the cookies and returns only the
CSRF token. SAML's callback sets the cookies and returns the safe user record
plus the CSRF token. Neither response exposes an app access token to JavaScript.

Cookie-mode backends expose `POST /auth/logout` below the configured API base
path. The request is CSRF-protected and expires the session, refresh, and CSRF
cookies. An OIDC provider logout may still follow it when the client also needs
to terminate the upstream identity-provider session.

## Same-origin assumption

Cookie delivery assumes the SPA and API share an origin. The `Secure` flag is
derived from the request scheme, so plain-HTTP local development still works
while production over HTTPS gets `Secure` automatically. `SameSite=Lax` blocks
the cookie from cross-site sub-requests.

## Runtime and generated clients

Cookie delivery is implemented by both `yaml-api run` and generated FastAPI
backends. Generated DRF and raw backends reject this delivery mode at build
time rather than emitting a partial authentication implementation.

The generic frontend pack sends same-origin credentials automatically, copies
the readable CSRF cookie into `x-csrf-token` on unsafe requests, never stores
the app token in `localStorage`, and calls the server logout route before
clearing its local authentication state.

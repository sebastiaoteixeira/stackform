# Cookie (BFF) session delivery

`session.delivery` selects how the app session token reaches the client. It
defaults to `token-url`, which returns the token in the login response body -
byte-identical to every prior release. Setting it to `cookie` switches the app
into a Backend-for-Frontend (BFF) posture: the session never touches
JavaScript-readable storage.

```yaml
session:
  delivery: cookie   # token-url (default) | code | cookie
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
`PATCH`, `DELETE`) issued by a request that carries a `session` cookie, the
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

## Same-origin assumption

Cookie delivery assumes the SPA and API share an origin. The `Secure` flag is
derived from the request scheme, so plain-HTTP local development still works
while production over HTTPS gets `Secure` automatically. `SameSite=Lax` blocks
the cookie from cross-site sub-requests.

## Testing gap

The `yaml-api run` dev server does not mount the generated provider/middleware
stack, so cookie delivery and CSRF are exercised at the generation, middleware,
and unit layers rather than through the dev server. The generic-pack SPA still
attaches `Authorization` headers from `localStorage`; wiring it to rely on the
same-origin cookie and to send the `x-csrf-token` header is left to the client
integrator following the contract above.

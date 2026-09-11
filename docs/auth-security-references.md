# Auth & Security References

Reference material behind the authentication/token design decisions in the generated apps,
and the standards/maturity models to evaluate them against.

## Token architecture: who issues the JWT?

This generator follows the **Backend-for-Frontend (BFF)** pattern: after an external IdP
(OIDC/Keycloak, SAML) authenticates the user, the **app mints its own session JWT** (HS256,
app secret) and discards the IdP token. The client uses the app JWT for subsequent API calls.

There are two mainstream patterns; this is one of them:

| Pattern | Session token | Immediate IdP revocation | Call downstream APIs as user | Simplicity |
| --- | --- | --- | --- | --- |
| App-issued (BFF) — *this generator* | App (HS256) | No (until app token expires) | No | Highest |
| IdP-token-direct (resource server) | IdP (verified via JWKS) | Yes | Yes | More moving parts |

## Sources for the design claims

- **Two patterns / BFF recommended for browser apps** — IETF *OAuth 2.0 for Browser-Based Apps* BCP. Names BFF, Token-Mediating Backend, and Browser-based OAuth Client as security/simplicity trade-offs.
  - https://datatracker.ietf.org/doc/draft-ietf-oauth-browser-based-apps/
  - https://oauth.net/2/browser-based-apps/
- **Authorization Code + PKCE recommended; avoid implicit/password grant** (issue #33) — *RFC 9700, Best Current Practice for OAuth 2.0 Security* (Jan 2025).
  - https://www.rfc-editor.org/info/rfc9700/
  - https://datatracker.ietf.org/doc/rfc9700/
- **JWT hardening: `alg:none`, algorithm confusion, validate `iss`** (relevant to HS256 today and a future RS256 move) — *RFC 8725, JSON Web Token Best Current Practices* (BCP 225).
  - https://datatracker.ietf.org/doc/html/rfc8725
- **New session token on auth; >=64 bits entropy; never put tokens in URLs** — OWASP ASVS / Session Management Cheat Sheet.
  - https://owasp.org/www-project-application-security-verification-standard/
  - https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html

## Maturity / assurance models to base evaluations on

Pick by what is being graded:

- **Grade the product/code (per-requirement checklist): OWASP ASVS.** Three levels (L1 -> L2 -> L3). V6 Authentication includes an "Authentication with an Identity Provider" section; V7 covers Session Management. Suggested target: **L2** for generated apps.
  - https://owasp.org/www-project-application-security-verification-standard/
- **Grade authentication strength: NIST SP 800-63B Authenticator Assurance Levels (AAL1/2/3).** AAL1 = single factor; AAL3 = hardware + phishing-resistant.
  - https://pages.nist.gov/800-63-4/sp800-63b.html
  - https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-63B-4.pdf
- **Grade the secure-development process (true maturity model): OWASP SAMM.** 0-3 maturity across governance, design, verification, operations. Use for program maturity, not a single app. Canonical site: owaspsamm.org.

## How to use them here

- Use **ASVS** as the concrete checklist for generated apps (target L2).
- Use **NIST 800-63B AAL** to decide required auth strength per deployment.
- Use **RFC 9700 + RFC 8725 + Browser-Based Apps BCP** as design references for auth/token code (inform issues #33 PKCE and #34 DPoP).
- Use **SAMM** only when assessing the framework project's process maturity.

## Known gaps / follow-ups

- **PKCE not emitted** by the generated OIDC client — GitHub issue #33.
- **DPoP not supported** (bearer tokens only) — GitHub issue #34.
- **HS256 shared secret**: fine for a single self-verifying app; prefer **RS256** if multiple services must verify tokens.
- **Secrets out of the spec and bundle**: `JWT_SECRET` and each confidential provider's `<PROVIDER>_CLIENT_SECRET` are runtime pydantic `SecretStr` env vars, never baked as literals; deploy bundles generate them at deploy time (Ansible `password` lookup), so no secret is committed to the spec or the bundle.
- **No refresh/revocation story**: app JWTs live until expiry; IdP-side logout does not invalidate them.
- **Token in URL**: the OIDC callback returns the app JWT via a `?token=` query parameter, which conflicts with ASVS session-management guidance (avoid tokens in URLs). Consider a one-time code exchange or an HttpOnly cookie.

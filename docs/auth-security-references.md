# Auth & Security References

Reference material behind the authentication/token design decisions in the generated apps,
and the standards/maturity models to evaluate them against.

## Token architecture: who issues the JWT?

By default, this generator follows the **Backend-for-Frontend (BFF)** pattern: after an
external IdP (OIDC/Keycloak, SAML) authenticates the user, the app mints its own session
JWT and discards the IdP token. Sessions support HS256 or RS256 signing and token or
HttpOnly-cookie delivery. An OIDC provider may instead use `trust: idp`, in which case
the API verifies the IdP token directly.

There are two mainstream patterns; this is one of them:

| Pattern | Session token | Immediate IdP revocation | Call downstream APIs as user | Simplicity |
| --- | --- | --- | --- | --- |
| App-issued (BFF) — default | App (HS256 or RS256) | No (until app token expires) | No | Highest |
| IdP-token-direct (`trust: idp`) | IdP (verified via JWKS) | Yes | Yes | More moving parts |

## Sources for the design claims

- **Two patterns / BFF recommended for browser apps** — IETF *OAuth 2.0 for Browser-Based Apps* BCP. Names BFF, Token-Mediating Backend, and Browser-based OAuth Client as security/simplicity trade-offs.
  - https://datatracker.ietf.org/doc/draft-ietf-oauth-browser-based-apps/
  - https://oauth.net/2/browser-based-apps/
- **Authorization Code + PKCE recommended; avoid implicit/password grant** (issue #33) — *RFC 9700, Best Current Practice for OAuth 2.0 Security* (Jan 2025).
  - https://www.rfc-editor.org/info/rfc9700/
  - https://datatracker.ietf.org/doc/rfc9700/
- **JWT hardening: `alg:none`, algorithm confusion, validate `iss`** — *RFC 8725, JSON Web Token Best Current Practices* (BCP 225).
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

## Implemented controls

- OIDC application clients support authorization-code `state`, PKCE S256, and DPoP.
- DPoP uses a persistent per-provider P-256 key, proof nonce retry, and bound-token checks.
- App sessions support HS256 or RS256, optional refresh-token rotation with reuse
  detection, and HttpOnly-cookie delivery with CSRF double-submit protection.
- OIDC callbacks return a one-time login code; session tokens are never placed in URLs.
- `JWT_SECRET`, signing keys, DPoP keys, and confidential provider client secrets are
  runtime `SecretStr` environment settings rather than literals baked into generated code.

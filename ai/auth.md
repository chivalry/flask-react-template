# Authentication

## Overview

Accounts sign in with an email and a password through `src_back/api/auth.py` and
`src_back/services/auth.py`, or through a sign-in provider, or with a passkey (both
below). Google, Sign in with Apple, and Facebook (#31) build on the same groundwork:

- `User` stores every email through `normalize_email()` in `src_back/models/user.py`
  (trimmed and lowercased), however the account is created or edited, and
  `find_user_by_email()` normalizes the address it looks up.
- `users.password_hash` is nullable: an account a sign-in provider creates has no
  password. `User.has_password`, and `has_password` in the user payload, say which.
  `authenticate_user` answers such an account, and an unknown email, exactly as it
  answers a wrong password, down to the one password-hash check each costs.
- `complete_login(user)` is the one place a sign-in starts. It refuses a deactivated
  account with `InactiveAccountError`, which the JSON routes answer with 403 and the
  provider callback with `account_inactive`, and otherwise makes the session permanent.
  Callers check the credential first, so only someone who proved it learns that the
  account is deactivated.
- `count_sign_in_methods(user)` counts the ways an account can sign in: a password, each
  linked provider, and each passkey. Code that removes one calls
  `lock_sign_in_methods(user)` before it looks the method up, then
  `require_another_sign_in_method(user)`, which raises `LastSignInMethodError` (409)
  instead of removing the last. The lock holds the account's row until the commit, so on
  PostgreSQL two removals at once take turns, and the second counts what the first left;
  SQLite ignores it.
- Self-registration loads `RegistrationSchema`, which accepts only an email and a
  password: `role` or `is_active` in the body answers 422, so nobody registers as an
  admin. A registered account is an active `user`.
- Every POST under `/api` must carry `X-Requested-With: XMLHttpRequest`
  (`ai/conventions.md`). A provider's callback may arrive as a cross-site POST without it,
  as Sign in with Apple's `form_post` does, so `oauth.callback` is exempt and checks
  its signed `state` instead.

An account without a password got its email address from the sign-in provider that
created it, which verified the address. No sign-in attaches a provider to an existing
account by its email unless `AUTO_LINK_BY_EMAIL` is on ("The linking policy"). A project
that turns it on must also verify the address of every account created another way, such
as by an invitation or a passkey-first sign-up, or linking a provider by email would hand
the account to whoever created it.

## Sign-in providers

A `Continue with <provider>` button runs the OAuth 2.0 and OpenID Connect
authorization-code flow on the backend. No token reaches the browser and none is stored. A
provider is enabled when its keys are set and `PUBLIC_BASE_URL` is known, and Apple only
when that is https; with none enabled, `/providers` answers `[]` and the sign-in pages
show only the password form. Google and Apple are the providers so far. A new one is one
`OAuthProvider` and one identity function in `src_back/services/oauth_providers.py`. Its
identity function receives the callback's parameters as well as the token response, which
is how Apple's first answer delivers the person's name.

### The flow

1. Login and Register render one link per enabled provider to
   `GET /api/v1/auth/oauth/<provider>/start?next=/path`. It is a full-page navigation, so
   this route and `callback` answer with redirects, never the JSON envelope.
2. `start` reads the session only when asked. `?link=1` on a same-origin navigation by a
   signed-in visitor, which is what the Account page's link sends, is linking, and `next`
   defaults to `/account`. Any other `?link=1` is refused with `invalid_state`, not run as
   a sign-in, which would leave the identity on a second account nothing can move it
   from. The refusal lands on the Account page, or on the sign-in page when no session
   remains, as when an Account tab outlives a sign-out elsewhere. Without `?link=1`,
   anyone is signing in, even with a live session, which `complete_login` replaces, and
   `next` defaults to `/`. It stores a transaction in the cookie below and redirects to
   the provider with `state`, `nonce`, and a PKCE challenge for a provider that supports
   one; Apple documents none.
3. The provider sends the browser back to `callback`, by GET, or by POST for Sign in with
   Apple. The callback trusts only the cookie: it compares `state`, exchanges the code,
   checks the ID token, resolves the account, and calls `complete_login`.
4. It clears the cookie and redirects to `PUBLIC_BASE_URL + next`. A failure redirects to
   `/login?error=<code>`, or `/account?error=<code>` when linking, and the page shows the
   message `src_front/src/utils/oauth.ts` holds for that code.

| Code               | Meaning                                                       |
| ------------------ | ------------------------------------------------------------- |
| `unknown_provider` | No enabled provider has that name                             |
| `cancelled`        | The person declined at the provider                           |
| `invalid_state`    | The answer or link request does not belong to this browser    |
| `expired`          | The transaction's cookie is gone or more than ten minutes old |
| `exchange_failed`  | The provider refused the code or could not be reached         |
| `invalid_token`    | The ID token, or the keys to check it, failed validation      |
| `email_required`   | The provider gave no email                                    |
| `email_unverified` | The provider has not verified the email                       |
| `link_required`    | The email belongs to an existing account                      |
| `already_linked`   | The identity, or the account's slot for it, is already taken  |
| `account_inactive` | The account has been deactivated or no longer exists          |

A failed token exchange or key fetch logs a warning; a wrong client secret shows up there
and nowhere else. OAuth's `access_denied` and Apple's `user_cancelled_authorize` both read
as `cancelled`.

### The transaction cookie

Production's session cookie is `SameSite=Strict`, and browsers never send such a cookie on
a navigation another site started, which is what the provider's redirect is. There is no
Redis, and gunicorn's workers share no memory. So `src_back/services/oauth_state.py` keeps
the transaction in a cookie of its own: signed with `SECRET_KEY`, `HttpOnly`, and good for
ten minutes. It holds nothing the browser's owner should not see. The callback's response
stores the session cookie. The browser may leave it off the redirect that follows, which
is harmless, because the SPA's `/me` call is same-site.

Over https the cookie is `__Host-oauth_txn`, with `SameSite=None; Secure` and `Path=/`.
`SameSite=None` lets a cross-site POST carry it. The signature proves this server issued a
transaction, not that it issued it to this browser, so the prefix does the rest: browsers
refuse such a cookie from a sibling host or plain http, which stops anyone planting their
own signed transaction and linking a victim's identity to their account. The session
cookie has no such prefix, so a sibling host can still sign a visitor in as someone else.
Over http the cookie is `oauth_txn`, `SameSite=Lax`, under `/api/v1/auth/oauth`, which a
GET callback still carries.

A callback that proved it belongs to the transaction clears the cookie, whatever the
outcome. One that did not leaves it, because any site can send a browser to the callback,
and that must not end a sign-in in progress. So two `start` requests in one browser
overwrite the cookie, the first callback fails with `invalid_state`, and the second
succeeds. Logging out clears the cookie too, so a link started before a sign-out cannot
finish after it.

The callback's GET is not throttled, because nginx counts only POSTs. One valid cookie can
replay it for ten minutes, and each replay holds a sync worker for a round trip to the
provider. A `limit_req` for it needs a location per provider, which is its own issue.

### The linking policy

`resolve_user()` in `src_back/services/oauth.py` fails closed:

1. A link matches the provider and its subject: sign in that account. While linking, one
   held by another account is `already_linked`. The subject decides, never the email: an
   address can change hands.
2. While linking: attach to the account that started the transaction, whatever the email
   says. An account has one link per provider, so a second is `already_linked`.
3. No email is `email_required`, and an unverified one is `email_unverified`.
4. A verified email with no account creates one, with no password and the `user` role.
5. A verified email that belongs to an account, with a password or without, is
   `link_required`: sign in another way, then link from the Account page. Registration
   never verifies an address, so attaching to an account with a password would leave
   whoever registered the victim's address a working password to the merged account. An
   account without a password can unlink its provider while it keeps a passkey, so
   attaching to one would let the identity its owner removed attach itself again. A
   project that verifies addresses at registration, and accepts that an unlink then no
   longer revokes a provider, can set `AUTO_LINK_BY_EMAIL`.

Rule 4 takes the provider's word. Google warns that `email_verified` records a past check:
for an address outside `@gmail.com` and Google Workspace, "ownership of the third party
email account may have since changed", and it recommends another challenge
([Google](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token)).
So rule 4 can create an account for a stale address, and the real owner's registration
then answers 409, which is no worse than anyone registering that address today. Under
rule 5, an account one provider created answers `link_required` to another provider's
sign-in until its owner links that provider from the Account page.

Link mode needs that same-origin request as well as the session, so another site cannot
start it, and a stale session cannot turn a sign-in into a link. Every link and unlink is
audited in `oauth_accounts`, admin-only, and a link made in the callback has no actor in
production, because the session does not reach it there. Unlinking the last way to sign in
is a 409.

Linking asks for no password or other fresh proof, and a link survives a password change.
To clear a compromised account, deactivate it and read its links' history on the Audit
tab. Filter by the `oauth_accounts` table rather than by user, because a link made in the
production callback has no actor, and match each entry's `user_id` to the account. Then
remove any link its owner does not recognize in a database shell before reactivating it:

```sql
DELETE FROM oauth_accounts WHERE user_id = <id> AND provider = '<provider>';
```

### Setting up Google

1. In the Google Cloud console, create an OAuth client of type Web application.
2. Add one authorized redirect URI per environment:
   `PUBLIC_BASE_URL + /api/v1/auth/oauth/google/callback`. The match is exact, including
   the port, and `scripts/worktree-setup.sh` moves the dev port per worktree, so register
   each one in use; any other shows `redirect_uri_mismatch` on Google's page.
3. `openid email profile` are non-sensitive scopes, so no app verification is needed.
   Publish the consent screen out of Testing, or only its test users can sign in. Showing
   the app's name and logo there takes Google's lighter
   [brand verification](https://support.google.com/cloud/answer/9110914).
4. Set `OAUTH_GOOGLE_CLIENT_ID` and `OAUTH_GOOGLE_CLIENT_SECRET` in the `.env`. Compose
   hands a container its values only when it creates one, so run `npm run deploy` on a
   server after changing them. A server provisioned before this has no such lines, which
   leaves Google off.

### Setting up Apple

Sign in with Apple needs a membership in the Apple Developer Program, and Apple accepts
a return URL only on a domain, never `localhost` or an IP address, over https. So
`build_registry()` leaves Apple off unless all four keys are set and `PUBLIC_BASE_URL`
is https, and once `PUBLIC_BASE_URL` is set it logs a warning when some keys are set and
Apple stays off anyway. Try it on staging (`ai/staging.md`). From a laptop it takes a
tunnel's https host name, registered with Apple and set as `PUBLIC_BASE_URL`, in front
of a stack that accepts it: the production stack run from an env file of its own, since
the dev `.env` cannot start it, or the dev stack once Vite's `server.allowedHosts` lists
the host name.

1. In Certificates, Identifiers & Profiles, enable Sign in with Apple on an App ID,
   which becomes the primary App ID for the site. A site without an app still needs one.
2. Create a Services ID. Its identifier, such as `com.example.web`, is
   `OAUTH_APPLE_CLIENT_ID`. Enable Sign in with Apple on it, choose the primary App ID,
   and under Website URLs list each environment's domain and its return URL,
   `PUBLIC_BASE_URL + /api/v1/auth/oauth/apple/callback`, so that one Services ID serves
   production and staging. Apple asks for no verification file, and an individual
   membership can register 10 website URLs, an organization 100 ([Apple][apple-web]).
3. Create a key with Sign in with Apple enabled for the primary App ID. Its Key ID is
   `OAUTH_APPLE_KEY_ID`, and its `.p8` file downloads only once. The Team ID shown in
   the membership details is `OAUTH_APPLE_TEAM_ID`.
4. Put the `.p8` file's text in `OAUTH_APPLE_PRIVATE_KEY` on one line, in double
   quotes, with `\n` between its lines. These commands print that line, to paste over
   the blank one in the server's `.env`:

    ```bash
    key=$(awk 'NF { printf "%s\\n", $0 }' AuthKey_ABC123DEFG.p8)
    printf 'OAUTH_APPLE_PRIVATE_KEY="%s"\n' "$key"
    ```

5. Run `npm run deploy`, or `npm run deploy:staging` on staging, because Compose hands a
   container its values only when it creates one. Then check the backend's log for a
   warning that begins `Sign in with Apple is off`. Keep the `.p8` outside the
   repository; `.gitignore` and `.dockerignore` refuse `*.p8` files as a backstop.

Things to know about Apple:

- Apple sends the person's name only with their first authorization of the site, in
  the `user` field of its POST, and the link keeps it in `oauth_accounts.display_name`;
  nothing shows it yet. If that first sign-in fails, as `link_required` does, the name
  is lost until the person stops using Sign in with Apple for the site in their Apple
  Account settings and authorizes it again. The field is unsigned, so only the name is
  read from it, and the email always comes from the ID token.
- Someone who hides their email signs in with a relay address under
  `privaterelay.appleid.com`, which matches no account here, so their first sign-in
  creates a new account instead of answering `link_required`. Someone who already has
  an account should sign in to it and link Apple from the Account page.
- Mail to a relay address bounces until the sending domain or address is registered
  under Sign in with Apple for Email Communication, with SPF or DKIM passing
  ([Apple][apple-relay]). Nothing in the template mails an account yet.
- Each token exchange mints its own client secret, good for five minutes, so the
  server's clock must be right; Ubuntu keeps it synchronized by default, with chrony
  since 25.10 and `systemd-timesyncd` before. A wrong Team ID or Key ID shows up only as
  `exchange_failed`, with a 400 from Apple's token endpoint in the backend's log; a wrong
  client id, or a return URL missing from the Services ID, stops on Apple's own page.
- Apple documents no PKCE, so the nonce is what ties Apple's ID token to the browser
  that started the sign-in, and a token without one is refused ([RFC 9700][rfc9700],
  section 4.5.3.2).
- Unlinking Apple here does not revoke the site at Apple, which the person does in
  their Apple Account settings, and Apple's server-to-server notifications, such as a
  relay address's forwarding being turned off, are not received.

[apple-web]: https://developer.apple.com/help/account/configure-app-capabilities/configure-sign-in-with-apple-for-the-web
[apple-relay]: https://developer.apple.com/help/account/configure-app-capabilities/configure-private-email-relay-service/
[rfc9700]: https://www.rfc-editor.org/rfc/rfc9700#section-4.5.3.2

## Passkeys

A passkey is a WebAuthn credential: a key pair whose private half stays in the person's
device or password manager, and whose public half `webauthn_credentials` keeps.
`src_back/services/passkeys.py` runs the two ceremonies with `webauthn` (py_webauthn),
`src_back/api/passkeys.py` serves them under `/api/v1/auth/passkeys`, and the browser
side is `@simplewebauthn/browser`.

### Signing in with a passkey

The sign-in page offers passkeys two ways, and neither asks for an email:

- The email field's `autocomplete="username webauthn"` lets the browser list the site's
  passkeys among its suggestions. The page starts this autofill ceremony when it mounts,
  renews it every four minutes, at once after a passkey picked from it fails, and after a
  failed or dismissed button sign-in, and stops it when it unmounts. A passkey picked and
  then dismissed at the device's prompt leaves the suggestions empty until the next
  renewal; the button works meanwhile.
- "Sign in with a passkey" opens the browser's own prompt, which ends the autofill
  ceremony, because a browser runs one at a time.

Both fetch `GET /login/options`, whose options name no credentials, so the browser offers
every passkey it holds for the site, and post the browser's answer to `/login/verify`.
The server finds the passkey by its credential id, requires the answer's user handle to be
the `uuid` of that passkey's account, checks the signature and the counter, records the
counter, the backup state, and `last_used_at`, and calls `complete_login`. Every refusal
is the same 401, `That passkey was not accepted.`, and a deactivated account gets its 403
only after its passkey checked out, as with a password. A dismissed prompt changes
nothing on the page.

Both ceremonies require user verification, so a passkey is two factors: the device and
its biometric, screen lock, or PIN. A security key without a PIN must be given one first;
Chrome offers to create it, and otherwise the key maker's tool sets it.

### Managing passkeys

The Account page's Passkeys section adds, renames, and deletes the signed-in account's
passkeys. Adding one (`GET /register/options`, then `POST /register/verify`) asks for an
optional nickname, then for the browser's prompt. The options exclude the account's
passkeys, so a device that already holds one says so. A passkey counts as a sign-in
method: deleting an account's last way to sign in is a 409, and unlinking a provider is
allowed while a passkey remains. Each add, rename, and delete is audited in
`webauthn_credentials`, admin-only, because the history route serves any signed-in account
a table that is not, and would show every account's passkeys; a sign-in is not audited.

### Relying party

`rp_settings()` derives the relying party from `PUBLIC_BASE_URL`:

- The RP ID is its host name, without the scheme or port: `example.com`, or `localhost`
  in development. A passkey works only for its RP ID, so moving the site to another domain
  orphans every passkey, and staging, on its own host, can use none of production's.
- The expected origin is its scheme, host, and port, rebuilt as browsers report it, with
  the host lowercased and a default port dropped. Give the host in ASCII: browsers report
  an internationalized name in its punycode form.
- `WEBAUTHN_RP_NAME` names the site in the browser's prompt.

Without `PUBLIC_BASE_URL` the four ceremony routes answer 404 with
`Passkeys are not enabled.`, as they do, with a warning in the log, when it does not
parse, as with a port that is not a number; listing, renaming, and deleting still work.
An IP address cannot be an RP ID, so a local setup uses `localhost`, which browsers treat
as secure over plain http.

### Challenges

A ceremony's challenge waits five minutes (`CHALLENGE_TTL_SECONDS`) in a signed cookie of
its own, which `src_back/services/passkey_state.py` writes: `__Host-passkey_register` or
`__Host-passkey_login`, `HttpOnly`, `Secure`, and `SameSite=Strict`, or, over plain http,
`passkey_register` or `passkey_login` under `/api/v1/auth/passkeys`. The options GET sets
it, and every answer from the verify POST clears it, so one answer spends it. A
registration challenge also names its account, so an answer that arrives after another
account signed in on the same browser is refused.

The challenge stays out of the Flask session on purpose. An options answer that rewrote
the session cookie could land after a sign-in that finished while it was in flight, and
sign the visitor out; a navigation from another site, which arrives without the
`SameSite=Strict` session cookie, would have replaced the session with one holding only
the challenge. The two options GETs also require `X-Requested-With`
(`ai/conventions.md`), so another site cannot replace a challenge by navigation, and the
sign-in page sends its options and verify requests one at a time, so the newest answer
always lands last.

A second sign-in tab replaces the first tab's challenge, so a passkey picked in the first
fails once. A browser's autofill request never times out, so the sign-in page renews its
offer every four minutes, before the challenge expires.

The cookie is signed, not stored, so whoever holds both a browser's challenge cookie and
an answer it just sent could replay the answer until the challenge expires. The counter
stops that for authenticators that count, but synced passkeys always report 0. Both
halves leave the browser only over TLS. A server-side record of spent challenges, such as
a table a scheduled job sweeps, would close the gap; the cookie costs no write per
sign-in.

### Lost passkeys and compromised accounts

An account whose only way in is a passkey on a lost device cannot sign in. An admin sets
a password for it on the Users screen; its owner signs in, deletes the lost passkey on the
Account page, and adds a new one. Until it is deleted, the lost passkey still signs in for
whoever unlocks that device.

Adding a passkey asks for no fresh proof, as linking a provider does not, and a passkey
survives a password change. To clear a compromised account, follow the steps for links
in "The linking policy", reading the `webauthn_credentials` history as well, and delete
each passkey its owner does not recognize:

```sql
DELETE FROM webauthn_credentials WHERE user_id = <id> AND id = <passkey id>;
```

### Trying passkeys locally

Chrome's DevTools have a WebAuthn panel (More tools, then WebAuthn). Enable the virtual
authenticator environment, add a `ctap2` authenticator, and tick Supports resident keys
and Supports user verification, which start unticked and without which every ceremony
fails here; then add and use passkeys on `http://localhost:<port>` as on a real device.
Chrome refuses WebAuthn on a page with a certificate error, so a self-signed https origin
will not do. The backend tests use `src_back/tests/software_authenticator.py`, which
answers both ceremonies with a real P-256 key.

## Sign-in throttling

In production, host nginx counts the POSTs each client address sends under
`/api/v1/auth/`: six may arrive at once, then one more every six seconds, and nginx
answers the rest with 429 and `{"error": "Too many attempts. Try again in a minute."}`
(`scripts/nginx-ssl.conf.template`). GETs never count, so `/me`, which every page load
sends, is never throttled. Development has no nginx and no limit.

- Every POST under `/api/v1/auth/` shares the budget, including a passkey's answers to
  `/passkeys/login/verify` and `/passkeys/register/verify`, and Sign in with Apple's
  callback, a POST, so an Apple sign-in costs one. The passkey options are GETs, so the
  sign-in page's autofill, which asks for them on every visit and every four minutes
  after, spends nothing. A passkey sign-in costs one POST, as a password sign-in does.
- The limit keys on the address nginx sees. Behind a CDN or another proxy, that is the
  proxy's address, so configure `real_ip_header` and `set_real_ip_from` first.
- Each app on a host has its own zone, named for `APP_NAME`. The `map` that picks out
  POSTs defines `$auth_post_client_address`, a name every site on the host shares, so
  another site that defines it must define it the same way.

To check it on the server, send eleven quick POSTs. The app answers the first six (422,
for the empty body) and nginx the other five (429):

```bash
for i in $(seq 11); do
  curl -s -o /dev/null -w '%{http_code} ' -X POST \
    -H 'X-Requested-With: XMLHttpRequest' "https://$DOMAIN/api/v1/auth/login"
done; echo
```

## Deactivated accounts

An admin deactivates an account instead of deleting it. On its next request its session
ends: `load_user` in `src_back/app.py` loads a deactivated account as nobody, and
Flask-Login's `UserMixin.is_authenticated` follows `is_active` as well, so
`@login_required` and `admin_required` answer 401 either way. A fresh login answers 403
`Account is inactive.` after the password check, and a provider sign-in lands on
`/login?error=account_inactive`.

- A new account must be committed, or given `is_active=True`, before `complete_login`:
  the column default applies only at INSERT, so an unsaved `User` reads `is_active` as
  `None` and is refused. Code that creates an account and signs it in at once, such as
  a provider callback (#29), commits first.
- Reactivating an account revives its old sessions within their lifetime, because
  Flask-Login keeps the account id in the cookie.

## First admin

The seed (`src_back/seed.py`) runs on every backend start and creates the first admin
from `ADMIN_EMAIL` and `ADMIN_PASSWORD`. It skips, printing why, when either is blank,
when any admin account exists, active or not, or when an account already has that email
in any letter case. Checking for an admin, not only for the email, keeps the bootstrap
to one run: an admin who changes their email on the Users screen would otherwise get a
second admin, with the bootstrap password, on the next start. The seed never changes or
promotes an existing account, so changing `ADMIN_PASSWORD` later resets nobody; change a
password on the Users screen instead.

`scripts/provision.sh` writes a random `ADMIN_PASSWORD` and a blank `ADMIN_EMAIL` into the
server's `.env`; fill in the email before the first deploy. Once an admin exists, the two
variables do nothing, so `ADMIN_PASSWORD` can be cleared from `.env` after that deploy. An
admin cannot deactivate or demote themself, so an active admin normally remains. If a
database edit leaves every admin deactivated, the seed will not create another;
reactivate one in a database shell (opened as in "Before deploying" below):

```sql
UPDATE users SET is_active = true WHERE email = '<email>';
```

## Configuration

- `PUBLIC_BASE_URL` is the origin browsers use: scheme, host, and port, with no path.
  A trailing slash is stripped. OAuth redirect URIs and the WebAuthn origin are built
  from it, never from the request.
    - Development and testing default it to `http://localhost:$FRONTEND_PORT`.
      `docker-compose.yml` passes the `.env` value to the backend with the same
      fallback. `scripts/up.sh` moves a blank or localhost value along with the ports,
      and `scripts/worktree-setup.sh` sets one per worktree.
    - In production `scripts/provision.sh` writes `https://$DOMAIN`, and
      `scripts/deploy.sh` refuses to deploy while it is empty. Unset anywhere else, it
      is `None`, and the app logs that OAuth sign-in and passkeys are disabled.
- `WEBAUTHN_RP_NAME` is the site name passkey prompts show. It falls back to
  `APP_NAME`, which is a slug, and then to `Flask React Template`, so set it to the
  product's display name.
- `APP_ENVIRONMENT` (`ai/staging.md`) gives every environment but production the
  session cookie `<environment>_session`, so a sign-in on staging never replaces
  production's.

A server provisioned before `PUBLIC_BASE_URL` and `WEBAUTHN_RP_NAME` existed lacks both
lines, and its next deploy stops with `PUBLIC_BASE_URL is empty`. Add them to
`~/$APP_NAME/.env`, then deploy again:

```text
PUBLIC_BASE_URL=https://<DOMAIN>
WEBAUTHN_RP_NAME=<display name>
```

## Email normalization migration

The `normalize_emails_and_nullable_password` migration folds every stored email with a
frozen copy of `normalize_email()`. Before it changes anything, it looks for accounts
whose emails would collide once folded. If any do, it stops, lists their ids and
emails, and leaves the database unchanged. `docker/entrypoint.sh` then exits, the
backend container restarts in a loop, and the deploy fails waiting for `/api/health`.
In development the same check runs when the backend container starts.

### Before deploying

Look for collisions while the old version is still serving. Open a database shell on
the server (`POSTGRES_USER` and `POSTGRES_DB` are in `.env`; in development the
command is `docker compose exec db psql -U app -d app`):

```bash
docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml \
  --env-file .env exec db psql -U <POSTGRES_USER> -d <POSTGRES_DB>
```

```sql
SELECT id, email, created_at FROM users
WHERE lower(trim(email)) IN (
    SELECT lower(trim(email)) FROM users
    GROUP BY lower(trim(email)) HAVING count(*) > 1
)
ORDER BY lower(trim(email)), id;
```

SQL `lower()` folds ASCII letters the way the migration does, which covers nearly every
address; the migration's own check is the authoritative one.

### Merging colliding accounts

For each group, keep one account and remove the others, in the same database shell:

1. Point the rows that reference an account you will remove at the one you keep.
   Foreign keys to `users.id` declare `ondelete`, so deleting an account cascades to,
   or nulls, whatever still references it.
2. Delete the extra accounts (`DELETE FROM users WHERE id IN (...);`), or give each one
   a different address.
3. If the migration already failed, restart the backend so its entrypoint runs the
   migration again, and rerun the deploy if it timed out:

    ```bash
    docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml \
      --env-file .env restart backend
    ```

If a merge goes wrong, the deploy's pre-migration dump (`ai/backups.md`) holds the
database as it was before the deploy.

### Downgrading

`flask db downgrade` restores `NOT NULL` on `password_hash`, and while any account has
no password it stops and lists them; give each one a password or delete it first.
Emails stay folded, because their original letter case is gone.

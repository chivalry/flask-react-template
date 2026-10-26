# Authentication

## Overview

Accounts sign in with an email and a password through `src_back/api/auth.py` and
`src_back/services/auth.py`. Sign-in providers (#29, #30, #31) and passkeys (#32) build
on this groundwork:

- `User` stores every email through `normalize_email()` in `src_back/models/user.py`
  (trimmed and lowercased), however the account is created or edited, and
  `find_user_by_email()` normalizes the address it looks up.
- `users.password_hash` is nullable: an account a sign-in provider creates has no
  password. `User.has_password`, and `has_password` in the user payload, say which.
  `authenticate_user` answers such an account, and an unknown email, exactly as it
  answers a wrong password, down to the one password-hash check each costs.
- `complete_login(user)` is the one place a sign-in starts, and it makes the session
  permanent.
- `count_sign_in_methods(user)` counts the ways an account can sign in. Code that
  removes one raises `LastSignInMethodError` (409) instead of removing the last.

An account without a password is trusted to own its email address, because only a
sign-in provider that verified the address creates one. Any new way to create such an
account, such as an invitation or a passkey-first sign-up, must verify the address
first; otherwise linking a provider by email would hand the account to whoever
created it.

## Configuration

- `PUBLIC_BASE_URL` is the origin browsers use: scheme, host, and port, with no path.
  A trailing slash is stripped. OAuth redirect URIs and the WebAuthn origin are built
  from it, never from the request.
    - Development and testing default it to `http://localhost:$FRONTEND_PORT`.
      `docker-compose.yml` sets it the same way, and `scripts/up.sh` and
      `scripts/worktree-setup.sh` rewrite it in `.env` along with the ports.
    - In production `scripts/provision.sh` writes `https://$DOMAIN`, and
      `scripts/deploy.sh` refuses to deploy while it is empty. Unset anywhere else, it
      is `None`, and the app logs that OAuth sign-in and passkeys are disabled.
- `WEBAUTHN_RP_NAME` is the site name passkey prompts show. It falls back to
  `APP_NAME`, which is a slug, and then to `Flask React Template`, so set it to the
  product's display name.

A server provisioned before these settings existed lacks both lines, and its next
deploy stops with `PUBLIC_BASE_URL is empty`. Add them to `~/$APP_NAME/.env`, then
deploy again:

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

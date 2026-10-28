# Staging

## Overview

Staging is a second deployment on the production host, where a feature, and a migration
above all, can be tried before it reaches production. It is a second clone of the
repository on the `staging` branch, with its own Compose project and its own nginx
site. `.env.staging.example` is a whole staging `.env`, and it sets staging apart from
production in:

- the domain, which has its own certificate;
- the names: `APP_NAME` and `COMPOSE_PROJECT_NAME` are production's plus `-staging`, and
  they name the clone under `$HOME`, the nginx site, the log directory, the containers,
  and the volumes;
- the loopback ports: `BACKEND_PORT=5001` and `FRONTEND_HOST_PORT=8081`, beside
  production's 5000 and 8080;
- the secrets: `SECRET_KEY`, `POSTGRES_PASSWORD`, and `ADMIN_PASSWORD`, none matching
  production's;
- the database and the uploads, which live in the volumes
  `<COMPOSE_PROJECT_NAME>_postgres_data` and `<COMPOSE_PROJECT_NAME>_uploads_data`;
- the session cookie: `APP_ENVIRONMENT=staging` names it `staging_session`, so a sign-in
  on staging never replaces production's;
- access: `STAGING_HTPASSWD` names an htpasswd file, and host nginx then asks for a
  password before it serves any page or API call.

It shares only `POSTGRES_USER` and `POSTGRES_DB` with production, so that a copy of
production's database keeps its owner; `scripts/copy-production.sh` refuses when they
differ.

Outside production, every page carries a `STAGING` badge at the bottom left, and the tab
title reads `STAGING · <app title>`. The sign-in page has both. The frontend learns the
environment from `/api/health`, which answers without a session with
`{"status": "ok", "environment": "staging"}`. A blank `APP_ENVIRONMENT` means
production, which shows neither.

A staging deploy leaves out what only production needs. It takes no pre-migration dump
and installs no backup timer or restore drill, because staging's data is a disposable
copy of production's, and `backup.sh` would push a staging dump through the host-wide
rclone remote, under whatever `BACKUP_PREFIX` staging's `.env` holds. It installs
neither the certbot renewal hook nor the certificate monitoring, because production's
hook and units cover every certificate on the host, and `certbot.timer` renews both. Of
the host's shared state, a staging deploy changes only its own nginx site.

One piece of shared state is touched even so. Both sites define the nginx `map` that
sets `$auth_post_client_address`, the variable the sign-in throttling keys on. nginx
keeps the definition it reads last, and it reads the enabled sites in alphabetical
order, so staging's, whose name is production's plus `-staging`, wins. A change to that
map therefore reaches production's sign-in throttling at the next staging deploy,
before the release. `ai/auth.md` already says every site must define it the same way.

## Setting up staging

Do this once production runs on the server. Steps 2 to 5 run as root on the server, and
step 6 can run from a laptop. `my-app` stands for production's `APP_NAME`, so staging's
is `my-app-staging`.

1. Add a DNS record for the staging host name that points at the server.
   `scripts/certbot-setup.sh` refuses until the name resolves to this machine.
2. Clone the `staging` branch and start from the example:

    ```bash
    git clone --branch staging <your-repo-url> ~/my-app-staging
    cd ~/my-app-staging
    cp .env.staging.example .env && chmod 600 .env
    ```

3. Fill in every blank in `.env`. Generate each secret with `openssl rand -hex 32`, and
   repeat `POSTGRES_PASSWORD` inside `DATABASE_URL`. Set both `CORS_ALLOWED_ORIGINS`
   and `PUBLIC_BASE_URL` to `https://<DOMAIN>`. `PRODUCTION_DIR` must name production's
   clone, and `STAGING_HTPASSWD` the file the next step creates.
4. Create the password file. `openssl passwd -6` asks for the password twice, and
   testers sign in as `tester` with it. The group and mode let nginx, which runs as
   `www-data` on Ubuntu, read the file:

    ```bash
    printf 'tester:%s\n' "$(openssl passwd -6)" > /etc/nginx/my-app-staging.htpasswd
    chown root:www-data /etc/nginx/my-app-staging.htpasswd
    chmod 640 /etc/nginx/my-app-staging.htpasswd
    ```

5. Run `bash scripts/certbot-setup.sh`. Because production's nginx already serves, it
   uses `--nginx` and stops nothing, so production stays up (`ai/tls.md`).
6. Deploy with `DEPLOY_HOST=root@example.com npm run deploy:staging` from a laptop, or
   with `bash scripts/deploy.sh --environment staging` on the server. Staging's backend
   creates its first admin from `ADMIN_EMAIL` and `ADMIN_PASSWORD` when it first starts.

## Deploying

`npm run deploy` runs `bash scripts/remote-deploy.sh`, and `npm run deploy:staging` runs
`bash scripts/remote-deploy.sh --environment staging`. Each takes the host from
`DEPLOY_HOST` or from an argument (`npm run deploy -- ubuntu@1.2.3.4`), reads `APP_NAME`
from the local `.env`, falling back to `.env.example`, and runs
`bash ~/<clone>/scripts/deploy.sh --environment <name>` on the server over SSH. The
clone is `~/<APP_NAME>` for production and `~/<APP_NAME>-<environment>` for any other
environment, and that clone's own `.env` sets `APP_NAME` to match.

`deploy.sh` takes the same `--environment <name>` option, which defaults to
`production`. Before `git pull`, and before it changes anything, it refuses to deploy
when:

- the environment is wrong. `--environment` must equal the clone's `APP_ENVIRONMENT`,
  where blank means production. Otherwise it stops with
  `asked to deploy production, but <clone>/.env deploys`, the clone's environment, and
  the `--environment` value to pass instead. So a staging clone holding production's
  `.env`, or a production clone switched to `staging`, is refused.
- the branch is wrong. The clone must be on `DEPLOY_BRANCH` from its `.env`, where blank
  means `main`: production's says `main`, and staging's says `staging`. Otherwise it
  stops with a message such as `<clone> is on staging, but its .env deploys main`, and
  `git switch main` there fixes it; a detached HEAD counts as the wrong branch. The
  guard matters because `git pull` takes whatever branch is checked out: a production
  clone left on the default branch, `staging`, would deploy unreleased commits, and a
  staging clone left on `main` would deploy production's.
- the password file is missing. When `.env` sets `STAGING_HTPASSWD`, the file it names
  must exist (step 4 of "Setting up staging").

Past those checks, a staging deploy takes the steps of a production deploy except the
pre-migration backup, the renewal hook, and the systemd units. Its nginx site is behind
the password when `STAGING_HTPASSWD` is set.

## Copying production into staging

Do this before releasing a migration that rewrites existing rows, so the migration
meets production's rows on staging first. Production's and staging's `db` containers
must be running. From the staging clone, as root on the server:

```bash
bash scripts/copy-production.sh
```

The script asks before it changes anything; `--yes` skips the question. It finds
production's clone through `PRODUCTION_DIR` in staging's `.env`. It refuses, with
`ERROR:` and the reason, before it changes anything, when:

- the argument is anything but `--yes`;
- the clone has no `.env`, or its `.env` does not say `APP_ENVIRONMENT=staging`, which
  is what stops it in production's clone with `only staging copies production.`;
- `PRODUCTION_DIR` is empty, or names a directory with no `.env`;
- production's `.env` deploys anything but production, where blank means production;
- either `COMPOSE_PROJECT_NAME` is empty, or the two are the same;
- `POSTGRES_USER` or `POSTGRES_DB` is empty or differs from production's, because the
  copy would not keep its owner;
- `APP_NAME` is empty, or staging's installed nginx site,
  `/etc/nginx/sites-available/<APP_NAME>`, has no `auth_basic_user_file` directive;
- the uploads volume `<COMPOSE_PROJECT_NAME>_uploads_data` of staging or of production
  does not exist, because `docker run -v` would create it empty;
- the answer to `Continue? [y/N]` is anything but `y` or `Y`, which prints
  `Nothing changed.`

Production is only read. In order, the script:

1. Stops staging's backend. From here on the backend starts again however the script
   ends.
2. Pipes a custom-format `pg_dump` of production's database, taken while production
   serves, into staging's `db` container. There `pg_restore` first turns the dump into
   SQL, so a truncated dump stops before `psql` runs, and `psql` then drops and
   recreates the `public` schema and loads the SQL in one transaction. Any error leaves
   staging's database as it was. Dropping the schema, rather than using
   `pg_dump --clean`, also removes the tables that only staging's newer migrations
   created; the backend's entrypoint creates them again from the copy.
3. Deletes everything in staging's uploads volume, then copies production's volume,
   mounted read-only, into it with `cp -a`, dotfiles included. If this step fails,
   staging holds production's database and a partial set of uploads.
4. Starts staging's backend and waits up to two minutes for `/api/health`. The
   entrypoint runs `db upgrade` first, so staging's migrations run on the copy, which is
   the rehearsal.

Testers then sign in to staging with their production passwords.

The copy holds every account's email and password hash, so staging must stay behind its
password. The script refuses until staging's installed nginx site asks for one; set
`STAGING_HTPASSWD` and deploy staging first.

## Branches and releases

`staging` is the default branch. Feature branches fork from `origin/staging` and their
PRs target it, so an issue closes when its PR merges into `staging`, before the change
reaches production: GitHub honors closing keywords only on the default branch.
`ai/conventions.md` states the rules; these are the commands.

A release is a PR from `staging` into `main`, merged with a merge commit. A squash or a
rebase rewrites staging's commits, so `main` would stop containing them and every later
release would conflict. After the merge the two branches must hold the same files, and
production deploys `main`:

```bash
gh pr create --base main --head staging --title "Release $(date +%F)" \
  --body "Promotes staging to production."
gh pr merge <number> --merge
git fetch origin
git diff --stat origin/staging origin/main   # must print nothing
npm run deploy
```

A hotfix goes the other way: branch from `origin/main`, open the PR against `main`,
merge it, and deploy production. Then bring the fix back into `staging` through a
throwaway branch, `sync-main-into-staging`, cut from `origin/main` and merged into
`staging` with `--merge`. Never use `main` itself as a PR's head, because GitHub can
delete a merged head branch, and this repository does:

```bash
git fetch origin
git switch -c issue-<number>-<slug> origin/main
# commit the fix, then:
git push -u origin issue-<number>-<slug>
gh pr create --base main --head issue-<number>-<slug> \
  --title "<title>" --body "<why>"
gh pr merge <number> --merge
npm run deploy
git fetch origin
git switch -c sync-main-into-staging origin/main
git push -u origin sync-main-into-staging
gh pr create --base staging --head sync-main-into-staging \
  --title "Bring main into staging" --body "Merges the hotfix back into staging."
gh pr merge <number> --merge
```

## Repository settings

Making `staging` the default branch is a one-time switch: cut `staging` from `main`,
make it the default, and run `git remote set-head origin --auto` in each clone, which
points `origin/HEAD` at `origin/staging`. Local fallow audits fall back to `origin/HEAD`
for their base.

```bash
git fetch origin
git push origin origin/main:refs/heads/staging
gh repo edit <owner>/<repo> --default-branch staging
git remote set-head origin --auto
```

Two rulesets enforce the rules above. `main` takes changes only through PRs merged with
a merge commit, with no approving review required, and neither `main` nor `staging` can
be deleted or force-pushed. Rulesets are free on public repositories; a private one
needs GitHub Pro or Team, and without them the rules are conventions.

For a project made from this template, GitHub copies only the default branch unless
"Include all branches" is ticked. If `main` is missing, create it from `staging` with
`git push origin origin/staging:refs/heads/main`, and keep `staging` as the default.

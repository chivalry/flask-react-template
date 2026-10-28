# TLS Certificates

## Overview

The site at `$DOMAIN` uses a Let's Encrypt certificate issued by certbot and served by
host nginx (not by a container), from the site config that `scripts/deploy.sh` renders
out of `scripts/nginx-ssl.conf.template`. The first certificate comes from
`scripts/certbot-setup.sh`, which reads `DOMAIN` and `CERTBOT_EMAIL` from the server's
`.env` (or takes `--email <addr>`). A second certificate on the host, staging's
(`ai/staging.md`), also comes from `certbot-setup.sh`, through the running nginx.
`certbot.timer`, installed with the certbot package, attempts renewal twice daily.

## Authenticators — the thing to get right

`certbot certonly --standalone` binds port 80 itself. That is correct for the FIRST
issuance on a bare server, where `provision.sh` has removed the default site and nginx
is serving no server block for the `--nginx` authenticator to use.

When nginx is already running with an enabled site, as on a host that serves
production, `certbot-setup.sh` requests the certificate through it with `--nginx` and
stops nothing, so issuing staging's certificate leaves production up.

Standalone is wrong for renewals. Unattended renewals run while nginx holds `:80`
permanently, so standalone can never rebind and every attempt fails with:

```text
Could not bind TCP port 80 because it is already in use by another process
```

Certbot persists the authenticator into `/etc/letsencrypt/renewal/<domain>.conf`, so a
standalone first issuance silently poisons every future renewal. In the project this
toolkit was ported from, that expired the production certificate after 66 consecutive
failures over a month, none of them reported. `certbot-setup.sh` therefore rewrites the
authenticator to `nginx` immediately after issuing and refuses to report success until
it has verified the change.

Always use `certonly`, never `run`: `scripts/deploy.sh` rewrites the nginx site config
from `scripts/nginx-ssl.conf.template` on every deploy, so certbot must not own it.

Check the stored authenticator with:

```bash
grep authenticator /etc/letsencrypt/renewal/$DOMAIN.conf
```

It must read `authenticator = nginx`.

## Reload after renewal

`certonly` fetches files but does not touch the running server, so nginx would keep
serving the old certificate from memory. `scripts/letsencrypt-deploy-hook.sh` is
installed by a production deploy to
`/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh` and reloads nginx whenever any
renewal succeeds.

## Monitoring

Two independent checks, because they fail differently.

1. `certbot.service` gets an `OnFailure=$APP_NAME-alert-certbot.service` drop-in at
   `/etc/systemd/system/certbot.service.d/$APP_NAME-onfailure.conf`, so any non-zero
   exit reports immediately — on the first failure, not 30 days later.
2. `$APP_NAME-cert-check.timer` runs `scripts/cert-check.sh` daily at 05:00 UTC. It
   warns when any certificate under `/etc/letsencrypt/live/` is within 21 days of
   expiry. This catches what the OnFailure hook cannot: the timer being disabled or
   dead, or a certificate nobody is renewing at all.

Both route through `scripts/alert.sh`, which posts to `ALERT_WEBHOOK_URL` from the
server's `.env`. `ALERT_WEBHOOK_FORMAT` is `text` (ntfy.sh), `slack`, or `discord`.
With no URL set, alerts are written to `/var/log/$APP_NAME/alert.log` and delivered
nowhere — the same silence that let the renewals above fail unnoticed, and not
sufficient on its own.

A production deploy installs all of this, the renewal hook included; a staging deploy
installs none of it, since production's hook and units cover every certificate on the
host. The unit files in `scripts/systemd/` carry `__APP_NAME__` and `__REPO_DIR__`
placeholders that are rendered at install time, so several apps on one host get
separate units, and their `OnFailure=` drop-ins merge instead of overwriting each other.

## Security headers

The HTTPS server in `scripts/nginx-ssl.conf.template` adds four headers to every
response, nginx's own error pages included, such as the 401 that basic auth sends when
`STAGING_HTPASSWD` is set:

- `Strict-Transport-Security: max-age=31536000`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy: frame-ancestors 'none'`

Only host nginx sends them. The frontend container's `docker/nginx.conf` sits behind it
and adds none, so no header arrives twice. A location that sets an `add_header` of its
own inherits none of the four and must repeat them.

HSTS is a promise kept for a year: a browser that has seen it refuses plain HTTP to
`$DOMAIN` and no longer lets a visitor click through a certificate error. An expired
certificate then takes the site down for every returning visitor instead of showing a
warning, which makes the monitoring above essential. Undoing HSTS needs a valid
certificate too: serve `max-age=0` over HTTPS until every returning browser has seen
it. The header leaves out `includeSubDomains`, which binds every subdomain, and
`preload`, which asks browsers to build the rule in; both are slow to undo, so add them
only once every subdomain serves HTTPS.

## Verifying

```bash
certbot certificates                  # expiry per cert
certbot renew --dry-run               # exercises the real renewal path
systemctl list-timers '*certbot*' '*cert-check*'
journalctl -u certbot.service -n 50
bash ~/$APP_NAME/scripts/cert-check.sh   # run the expiry check now
```

Confirm what is actually served, which can differ from what is on disk if nginx was not
reloaded:

```bash
echo | openssl s_client -connect $DOMAIN:443 \
  -servername $DOMAIN 2>/dev/null | openssl x509 -noout -dates
curl -sI https://$DOMAIN/ |
  grep -iE '^(strict-transport|x-content-type|referrer|content-security)'
```

## Manual recovery if a certificate has already expired

```bash
certbot certonly --nginx -d $DOMAIN \
  --non-interactive --agree-tos -m $CERTBOT_EMAIL --force-renewal
systemctl reload nginx
```

This also repairs a poisoned `standalone` authenticator, since `certonly --nginx`
rewrites the renewal config.

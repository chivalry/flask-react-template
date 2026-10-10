#!/usr/bin/env bash
# Reload nginx after certbot renews any certificate.
#
# certbot certonly fetches cert files but does not touch the running server, so
# without this hook nginx keeps serving the previous certificate from memory until
# something reloads it — which, before this existed, meant the next deploy.
#
# Installed to /etc/letsencrypt/renewal-hooks/deploy/ by deploy.sh, so it applies to
# every certificate on the host. certbot runs deploy hooks only when a renewal
# actually succeeds.
set -euo pipefail

systemctl reload nginx

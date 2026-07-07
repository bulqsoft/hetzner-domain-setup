#!/usr/bin/env bash

set -Eeuo pipefail

APP_NAME="Hetzner Domain Setup Tool"

DOMAIN=""
WEBROOT=""
EMAIL=""
EXPECTED_IP=""
ENABLE_SSL=true
FORCE_INDEX=false
ALIASES=()

usage() {
    cat <<USAGE
$APP_NAME

Usage:
  sudo ./setup-domain.sh --domain example.com --root /var/www/example --expected-ip 1.2.3.4 --email admin@example.com

Required:
  --domain        Main domain, example: cuervo-investments.com

Optional:
  --root          Website root folder. Default: /var/www/domain-with-dashes
  --expected-ip   Check DNS points to this IP before setup
  --email         Email for Let's Encrypt SSL
  --alias         Extra domain, example: www.example.com
  --no-ssl        Skip SSL setup
  --force-index   Replace existing index.html with templates/coming-soon.html
  -h, --help      Show help

Examples:
  sudo ./setup-domain.sh --domain cuervo-investments.com --root /var/www/cuervo-investments --expected-ip 46.224.190.101 --email info@bulqsoft.com --force-index

  sudo ./setup-domain.sh --domain staging.example.com --root /var/www/example-staging --expected-ip 46.224.184.77 --email info@bulqsoft.com --force-index

  sudo ./setup-domain.sh --domain example.com --root /var/www/example --alias www.example.com --email info@bulqsoft.com --force-index
USAGE
}

log() {
    echo ""
    echo "==> $1"
}

warn() {
    echo ""
    echo "WARNING: $1"
}

fail() {
    echo ""
    echo "ERROR: $1" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

safe_name() {
    echo "$1" | tr '.' '-' | tr -cd 'A-Za-z0-9_-'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)
            DOMAIN="${2:-}"
            shift 2
            ;;
        --root|--webroot)
            WEBROOT="${2:-}"
            shift 2
            ;;
        --email)
            EMAIL="${2:-}"
            shift 2
            ;;
        --expected-ip)
            EXPECTED_IP="${2:-}"
            shift 2
            ;;
        --alias)
            ALIASES+=("${2:-}")
            shift 2
            ;;
        --no-ssl)
            ENABLE_SSL=false
            shift
            ;;
        --force-index)
            FORCE_INDEX=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "Unknown option: $1"
            ;;
    esac
done

[[ -n "$DOMAIN" ]] || fail "Missing --domain"
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || fail "Invalid domain format: $DOMAIN"

if [[ -z "$WEBROOT" ]]; then
    WEBROOT="/var/www/$(safe_name "$DOMAIN")"
fi

if [[ "$WEBROOT" != /var/www/* ]]; then
    fail "--root must be inside /var/www for safety. Example: /var/www/example"
fi

if [[ "$EUID" -ne 0 ]]; then
    fail "Please run this script with sudo"
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
TEMPLATE_FILE="$SCRIPT_DIR/templates/coming-soon.html"

[[ -f "$TEMPLATE_FILE" ]] || fail "Template not found: $TEMPLATE_FILE"

OWNER="${SUDO_USER:-root}"
SITE_NAME="$(safe_name "$DOMAIN")"
SITE_AVAILABLE="/etc/nginx/sites-available/$SITE_NAME"
SITE_ENABLED="/etc/nginx/sites-enabled/$SITE_NAME"
SERVER_NAMES="$DOMAIN"

for alias in "${ALIASES[@]}"; do
    [[ "$alias" =~ ^[A-Za-z0-9.-]+$ ]] || fail "Invalid alias format: $alias"
    SERVER_NAMES="$SERVER_NAMES $alias"
done

require_cmd nginx
require_cmd systemctl
require_cmd curl
require_cmd getent
require_cmd awk
require_cmd sort

log "Setup summary"
echo "Domain:       $DOMAIN"
echo "Aliases:      ${ALIASES[*]:-none}"
echo "Web root:     $WEBROOT"
echo "Owner:        $OWNER:www-data"
echo "Nginx file:   $SITE_AVAILABLE"
echo "SSL enabled:  $ENABLE_SSL"
echo "Expected IP:  ${EXPECTED_IP:-not checked strictly}"

log "Checking DNS"
RESOLVED_IPS="$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u | tr '\n' ' ' || true)"

if [[ -z "$RESOLVED_IPS" ]]; then
    warn "Could not resolve DNS for $DOMAIN yet."
else
    echo "$DOMAIN resolves to: $RESOLVED_IPS"
fi

if [[ -n "$EXPECTED_IP" ]]; then
    if echo "$RESOLVED_IPS" | grep -qw "$EXPECTED_IP"; then
        echo "DNS check passed: $DOMAIN points to $EXPECTED_IP"
    else
        fail "DNS check failed. $DOMAIN does not point to $EXPECTED_IP yet. Current: ${RESOLVED_IPS:-none}"
    fi
fi

log "Checking duplicate Nginx server_name"
if grep -R "server_name .*${DOMAIN}" /etc/nginx/sites-available /etc/nginx/sites-enabled >/dev/null 2>&1; then
    warn "$DOMAIN already appears in an existing Nginx config. The script will still continue, but check duplicates if nginx -t fails."
fi

log "Creating web root"
mkdir -p "$WEBROOT"
chown -R "$OWNER:www-data" "$WEBROOT"
chmod 755 "$WEBROOT"

if [[ ! -f "$WEBROOT/index.html" || "$FORCE_INDEX" == true ]]; then
    log "Copying Coming Soon page"
    cp "$TEMPLATE_FILE" "$WEBROOT/index.html"
else
    echo "index.html already exists. Not overwriting. Use --force-index to replace it."
fi

chown "$OWNER:www-data" "$WEBROOT/index.html"
chmod 644 "$WEBROOT/index.html"

log "Creating Nginx config"

if [[ -f "$SITE_AVAILABLE" ]]; then
    BACKUP_FILE="${SITE_AVAILABLE}.backup.$(date +%Y%m%d%H%M%S)"
    cp "$SITE_AVAILABLE" "$BACKUP_FILE"
    echo "Existing config backed up to: $BACKUP_FILE"
fi

cat > "$SITE_AVAILABLE" <<NGINX
server {
    listen 80;
    listen [::]:80;

    server_name $SERVER_NAMES;

    root $WEBROOT;
    index index.html index.htm;

    access_log /var/log/nginx/$SITE_NAME-access.log;
    error_log /var/log/nginx/$SITE_NAME-error.log;

    location / {
        try_files \$uri \$uri/ =404;
    }
}
NGINX

ln -sfn "$SITE_AVAILABLE" "$SITE_ENABLED"

log "Testing Nginx"
nginx -t

log "Reloading Nginx"
systemctl reload nginx

log "Testing HTTP"
curl -I --max-time 15 "http://$DOMAIN" || true

if [[ "$ENABLE_SSL" == true ]]; then
    require_cmd certbot

    log "Requesting SSL certificate"

    CERTBOT_DOMAINS=(-d "$DOMAIN")

    for alias in "${ALIASES[@]}"; do
        CERTBOT_DOMAINS+=(-d "$alias")
    done

    if [[ -n "$EMAIL" ]]; then
        certbot --nginx "${CERTBOT_DOMAINS[@]}" --redirect --agree-tos --email "$EMAIL" --non-interactive
    else
        warn "No --email provided. Running Certbot in interactive mode."
        certbot --nginx "${CERTBOT_DOMAINS[@]}" --redirect
    fi

    log "Testing Nginx after SSL"
    nginx -t

    log "Reloading Nginx after SSL"
    systemctl reload nginx

    log "Testing HTTPS"
    curl -I --max-time 15 "https://$DOMAIN" || true

    log "Testing HTTP redirect"
    curl -I --max-time 15 "http://$DOMAIN" || true
fi

log "Done"
echo "Website root: $WEBROOT"
echo "Nginx config: $SITE_AVAILABLE"
echo "Enabled site: $SITE_ENABLED"
echo "URL: https://$DOMAIN"
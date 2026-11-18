"""Safe, explicit staging provisioning engine for Bulqsoft.

Only the MCP adapter should expose these operations. Approval tokens must be
issued by a separate, authenticated owner-approval service, never by a model.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import time


PROJECT = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$")
LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
SAFE_PATH = re.compile(r"^/[a-zA-Z0-9_./-]+$")


class SiteError(ValueError):
    """An unsafe, unauthorized or invalid staging operation."""


def _hostname(value: str) -> str:
    name = value.strip().lower().rstrip(".")
    if len(name) > 253 or len(name) < 4 or ".." in name:
        raise SiteError("Invalid DNS hostname")
    labels = name.split(".")
    if len(labels) < 3 or any(not LABEL.fullmatch(part) for part in labels):
        raise SiteError("Use a valid subdomain, not an apex domain")
    return name


def _env_csv(name: str) -> tuple[str, ...]:
    return tuple(v.strip().lower().rstrip(".") for v in os.environ.get(name, "").split(",") if v.strip())


def _clean_project(value: str) -> str:
    project = value.strip().lower()
    if not PROJECT.fullmatch(project):
        raise SiteError("Project ID must be a simple 1-48 character slug")
    return project


def _validate_ip(value: str) -> str:
    try:
        ip = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise SiteError("A valid IPv4 address is required") from exc
    if not ip.is_global:
        raise SiteError("Server IP must be publicly routable")
    return str(ip)


def _safe_absolute_path(value: str) -> Path:
    if not SAFE_PATH.fullmatch(value) or ".." in Path(value).parts:
        raise SiteError("Unsafe filesystem path")
    return Path(value)


def plan_site(project: str, hostname: str, server_ipv4: str) -> dict:
    """Validate scope and return a deterministic, non-mutating deployment plan."""
    slug, host, ip = _clean_project(project), _hostname(hostname), _validate_ip(server_ipv4)
    allowed_domains = _env_csv("BULQ_ALLOWED_DNS_SUFFIXES")
    allowed_ips = _env_csv("BULQ_ALLOWED_SERVER_IPS")
    if not allowed_domains or not any(host.endswith("." + suffix) for suffix in allowed_domains):
        raise SiteError("Hostname is outside explicitly allowed DNS zones")
    if ip not in allowed_ips:
        raise SiteError("IP is not on the configured server allowlist")

    root = _safe_absolute_path(os.environ.get("BULQ_SITE_ROOT", "/var/www/bulq-sites"))
    nginx_dir = _safe_absolute_path(os.environ.get("BULQ_NGINX_AVAILABLE", "/etc/nginx/sites-available"))
    enabled_dir = _safe_absolute_path(os.environ.get("BULQ_NGINX_ENABLED", "/etc/nginx/sites-enabled"))
    preview_auth = _safe_absolute_path(os.environ.get("BULQ_PREVIEW_HTPASSWD", "/etc/nginx/bulq-preview.htpasswd"))
    email = os.environ.get("BULQ_CERTBOT_EMAIL", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", email):
        raise SiteError("Configure BULQ_CERTBOT_EMAIL before provisioning")

    details = {
        "version": 1, "project": slug, "hostname": host, "server_ipv4": ip,
        "webroot": str(root / slug / "staging"),
        "nginx_available": str(nginx_dir / ("bulq-" + slug + ".conf")),
        "nginx_enabled": str(enabled_dir / ("bulq-" + slug + ".conf")),
        "preview_auth": str(preview_auth),
        "certbot_email": email,
        "dns_record": {"type": "A", "name": host[:-(len(max((s for s in allowed_domains if host.endswith("." + s)), key=len)) + 1)], "fqdn": host, "value": ip},
    }
    payload = json.dumps(details, sort_keys=True, separators=(",", ":"))
    details["plan_id"] = hashlib.sha256(payload.encode()).hexdigest()
    details["requires_approval"] = True
    details["note"] = "DNS must first be managed by the authoritative DNS provider; existing records are never replaced."
    return details


def issue_approval(plan_id: str, *, now: int | None = None) -> str:
    """PRIVATE server-admin helper; do not expose this function through MCP."""
    key = os.environ.get("BULQ_APPROVAL_SECRET", "")
    if len(key) < 32:
        raise SiteError("Approval secret must be at least 32 characters")
    ts = int(time.time() if now is None else now)
    nonce = secrets.token_hex(16)
    payload = f"staging:{plan_id}:{ts}:{nonce}"
    mac = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{ts}:{nonce}:{mac}"


def _consume_approval(plan_id: str, token: str, *, now: int | None = None) -> None:
    key = os.environ.get("BULQ_APPROVAL_SECRET", "")
    if len(key) < 32:
        raise SiteError("Approval secret missing")
    try:
        timestamp, nonce, signature = token.split(":")
        ts = int(timestamp)
    except (ValueError, AttributeError) as exc:
        raise SiteError("Approval token is invalid") from exc
    current = int(time.time() if now is None else now)
    if not re.fullmatch(r"[a-f0-9]{32}", nonce) or not re.fullmatch(r"[a-f0-9]{64}", signature):
        raise SiteError("Approval token is malformed")
    if not 0 <= current - ts <= 300:
        raise SiteError("Approval token expired or comes from the future")
    payload = f"staging:{plan_id}:{ts}:{nonce}"
    expected = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise SiteError("Approval signature does not match this plan")
    ledger = _safe_absolute_path(os.environ.get("BULQ_APPROVAL_LEDGER", "/var/lib/bulqsoft/site-approvals"))
    ledger.mkdir(parents=True, mode=0o700, exist_ok=True)
    marker = ledger / hashlib.sha256(token.encode()).hexdigest()
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SiteError("This approval was already used") from exc
    with os.fdopen(fd, "w") as out:
        out.write(plan_id + "\n")


def _verify_dns(host: str, ip: str) -> None:
    try:
        resolved = {info[4][0] for info in socket.getaddrinfo(host, None, family=socket.AF_INET)}
    except socket.gaierror as exc:
        raise SiteError("DNS record is not resolving yet") from exc
    if resolved != {ip}:
        raise SiteError(f"DNS points to {sorted(resolved)}, not solely to the approved server")


def _run(*args: str) -> None:
    subprocess.run(list(args), check=True, timeout=120, capture_output=True, text=True)


def provision_staging(project: str, hostname: str, server_ipv4: str, approval_token: str) -> dict:
    """Provision ONLY a brand-new, protected staging site; never overwrite a live site."""
    plan = plan_site(project, hostname, server_ipv4)
    if os.geteuid() != 0:
        raise SiteError("Server-side staging worker must run with required privileges")
    _verify_dns(plan["hostname"], plan["server_ipv4"])
    auth_file = Path(plan["preview_auth"])
    if not auth_file.is_file() or auth_file.is_symlink():
        raise SiteError("Staging is blocked until a valid preview password file exists")
    root = Path(plan["webroot"])
    available = Path(plan["nginx_available"])
    enabled = Path(plan["nginx_enabled"])
    if root.exists() or root.is_symlink() or available.exists() or available.is_symlink() or enabled.exists() or enabled.is_symlink():
        raise SiteError("Existing staging or Nginx config detected. Refusing to overwrite.")
    for directory in (root.parent, root.parent.parent, available.parent, enabled.parent):
        if directory.is_symlink():
            raise SiteError("A managed parent directory is a symlink")
    _consume_approval(plan["plan_id"], approval_token)

    site_created = config_created = link_created = False
    try:
        root.mkdir(parents=True, mode=0o755, exist_ok=False)
        site_created = True
        root.chmod(0o755)
        landing = ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
                   "<meta name='robots' content='noindex,nofollow'>"
                   "<title>Bulqsoft staging</title></head><body><h1>Private website preview</h1>"
                   f"<p>{html.escape(plan['hostname'])}</p></body></html>\n")
        # Only the active revision is served. The release worker switches this
        # symlink atomically without changing Nginx configuration.
        bootstrap = root / "releases" / "bootstrap"
        bootstrap.mkdir(parents=True, mode=0o755)
        (bootstrap / "index.html").write_text(landing, encoding="utf-8")
        (bootstrap / "index.html").chmod(0o644)
        (root / "current").symlink_to("releases/bootstrap")
        (root / ".bulq-managed.json").write_text(
            json.dumps({"version": 1, "project": plan["project"],
                        "hostname": plan["hostname"]}, sort_keys=True),
            encoding="utf-8",
        )
        nginx_config = (
            "server {\n"
            "    listen 80;\n"
            f"    server_name {plan['hostname']};\n"
            f"    root {root / 'current'};\n"
            "    index index.html;\n"
            "    add_header X-Robots-Tag 'noindex, nofollow' always;\n"
            "    auth_basic 'Private Bulqsoft preview';\n"
            f"    auth_basic_user_file {auth_file};\n"
            "    location / { try_files $uri $uri/ =404; }\n"
            "}\n"
        )
        with available.open("x", encoding="utf-8") as config:
            config_created = True
            config.write(nginx_config)
        enabled.symlink_to(available)
        link_created = True
        _run("nginx", "-t")
        _run("systemctl", "reload", "nginx")
        _run("certbot", "--nginx", "--non-interactive", "--agree-tos", "--redirect",
             "--email", plan["certbot_email"], "-d", plan["hostname"])
        _run("nginx", "-t")
        _run("systemctl", "reload", "nginx")
    except Exception:
        # Only artifacts created by THIS invocation are removed. No pre-existing site is modified.
        if link_created:
            enabled.unlink(missing_ok=True)
        if config_created:
            available.unlink(missing_ok=True)
        if site_created:
            shutil.rmtree(root)
        try:
            _run("nginx", "-t")
            _run("systemctl", "reload", "nginx")
        except Exception:
            pass
        raise
    return {"status": "staging_provisioned", "url": "https://" + plan["hostname"],
            "plan_id": plan["plan_id"], "protected": True, "production_live": False}

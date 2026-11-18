# Bulqsoft website automation: staging MVP

This branch adds a **server-side staging worker** with an MCP adapter to the
existing Hetzner domain setup repository. It does not change production servers
on its own. It is **not yet** the complete AI website factory.

## Actions implemented

- Validate a proposed site ID, subdomain, permitted DNS zone and server IPv4
- Produce a deterministic, read-only plan with a SHA-256 plan ID
- Require a server-side, time-limited HMAC approval for the exact plan
- Require the public DNS A record to resolve exclusively to the chosen server
- Reject overwriting an existing webroot, symlink or Nginx site
- Install a private, Basic Auth-protected staging placeholder, use Nginx and Certbot
- Roll back newly created files on failure (no changes to unrelated sites)
- Expose MCP tools `prepare_staging` and `execute_approved_staging`

**Not yet implemented:** DNS record creation (use the currently connected
Openprovider or future Versio DNS action where authoritative), AI prompt-to-code,
GitHub commit publishing, customer preview revisions, Odoo payments,
production promotion, automated secret provisioning, and server installation.

## Installation prerequisites (only by an authorized server operator)

- Python 3.11+, Nginx, Certbot with Nginx plugin, a dedicated low-privilege
  deployment service, restricted file permissions and a trusted MCP transport
- The server-side worker needs narrowly scoped sudo/polkit for approved commands;
  do **not** run a public HTTP MCP endpoint as root
- Preconfigure an Nginx htpasswd file, ideally outside any public web directory
- Configure environment variables in a private secrets manager (never GitHub):

```text
BULQ_ALLOWED_DNS_SUFFIXES=bulqsoft.com,customer-approved-zone.example
BULQ_ALLOWED_SERVER_IPS=46.224.190.101
BULQ_SITE_ROOT=/var/www/bulq-sites
BULQ_NGINX_AVAILABLE=/etc/nginx/sites-available
BULQ_NGINX_ENABLED=/etc/nginx/sites-enabled
BULQ_PREVIEW_HTPASSWD=/etc/nginx/bulq-preview.htpasswd
BULQ_CERTBOT_EMAIL=info@bulqsoft.com
BULQ_APPROVAL_SECRET=<random-secret-at-least-32-characters>
BULQ_APPROVAL_LEDGER=/var/lib/bulqsoft/site-approvals
```

The owner-approval backend must validate the human owner's explicit consent
to a specific displayed plan before it calls the **backend-only**
`python -m automation.admin_approve --plan-id <SHA256>`. The minting helper
is intentionally not available to ChatGPT tools. A token expires after 5 minutes
and can be consumed once.

MCP adapter (trusted stdio transport only):

```bash
python -m pip install -r automation/requirements.txt
python -m automation.mcp_server
```

Offline tests:

```bash
python -m unittest discover -s automation/tests -v
```

## Operational safeguards

1. Confirm the authoritative DNS provider before making records. Do not switch
   nameservers or change an existing mail/domain record as part of provisioning.
2. Never deploy the worker on an internet-exposed or shared MCP transport.
3. Treat staging as a private environment. Only approved owners may issue tokens.
4. Do not point the actual `build.bulqsoft.com` service to an automatically
   generated staging site without checking existing applications/virtual hosts.
5. Production publishing requires a **separate explicit approval** and is not
   exposed by the current tools.
6. Ensure service logs/audit records are retained in the hosting environment.

## Roadmap to full automation

A separate trusted deployment service must receive GitHub artifact references
and AI-generated code, scan and build in isolation, publish staging versions,
accept revision prompts, and promote a reviewed version to production only after
approval/payment checks. The customer-facing platform and the owner's ChatGPT
path can both use the same service with distinct identities and permissions.

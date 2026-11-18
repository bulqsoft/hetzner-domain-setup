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
- Obtain a Let's Encrypt certificate through the isolated webroot challenge and configure private HTTPS without letting Certbot rewrite other Nginx sites
- Provide an atomically switched, immutable static staging release path with revision checks
- Expose MCP tools `prepare_staging`, `execute_approved_staging`, `inspect_staging_release`, `prepare_site_release` and `execute_approved_site_release`

**Not yet implemented:** automatic DNS record creation as part of this worker (use the existing Openprovider connector where authoritative), prompt-to-code generation, GitHub artifact publishing, customer prompt/revision interface, Odoo payments, production promotion, owner approval-service integration, and installation/registration of these tools on the real MCP host. A manual test plan for `staging.bedgadgets.nl` is in [DEPLOY_BEDGADGETS.md](DEPLOY_BEDGADGETS.md).

## Installation prerequisites (only by an authorized server operator)

- Python 3.11+, Nginx, Certbot with Nginx plugin, a dedicated low-privilege
  deployment service, restricted file permissions and a trusted MCP transport
- Keep the MCP server and release worker non-root, using a distinct, dedicated release identity. The privileged provisioning entrypoint `/usr/local/sbin/bulq-staging-provision` must be root-owned, immutable to the MCP process, and invoked only by a narrowly scoped sudo policy. No generic shell/SSH tool should be exposed through MCP. Do **not** run a public HTTP MCP endpoint as root.
- Preconfigure an Nginx htpasswd file, ideally outside any public web directory
- Configure environment variables in a private secrets manager (never GitHub):

```text
BULQ_ALLOWED_DNS_SUFFIXES=bedgadgets.nl,other-explicitly-approved-zones.example
BULQ_ALLOWED_SERVER_IPS=46.224.190.101
BULQ_SITE_ROOT=/var/www/bulq-sites
BULQ_RELEASE_USER=bulq-release
BULQ_NGINX_AVAILABLE=/etc/nginx/sites-available
BULQ_NGINX_ENABLED=/etc/nginx/sites-enabled
BULQ_PREVIEW_HTPASSWD=/etc/nginx/bulq-preview.htpasswd
BULQ_CERTBOT_EMAIL=info@bulqsoft.com
BULQ_APPROVAL_SECRET=<random-secret-at-least-32-characters>
BULQ_APPROVAL_LEDGER=/var/lib/bulqsoft/site-approvals
```

For the non-root release worker, use a **separate** owned/writable approval ledger and dedicated secret configuration. Do not allow the release worker to create or overwrite the root helper's approval ledger. The dedicated user must not be able to write Nginx configuration or private keys. The managed staging folder is assigned to that user by provisioning only after the HTTPS configuration succeeds.

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
2. Never deploy the worker on an internet-exposed or shared MCP transport; this branch currently runs only as a trusted stdio server and is **not registered** with the existing Bulqsoft MCP runtime.
3. Treat staging as a private environment. Only approved owners may issue tokens.
4. Do not point the actual `build.bulqsoft.com` service to an automatically
   generated staging site without checking existing applications/virtual hosts.
5. Production publishing requires a **separate explicit approval** and is not
   exposed by the current tools.
6. Ensure service logs/audit records are retained in the hosting environment. HTTPS issuance and automated renewal must be verified on the host (`certbot renew --dry-run` and Certbot timer). Do not expose a new public port unless a specific architectural requirement proves it necessary; route by Nginx host name on 443.

## Roadmap to full automation

A separate trusted deployment service must receive GitHub artifact references
and AI-generated code, scan and build in isolation, publish staging versions,
accept revision prompts, and promote a reviewed version to production only after
approval/payment checks. The customer-facing platform and the owner's ChatGPT
path can both use the same service with distinct identities and permissions.

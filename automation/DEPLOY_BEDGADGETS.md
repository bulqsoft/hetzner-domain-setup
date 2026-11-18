# BedGadgets staging rollout — installation checklist

**Status:** DNS A record for `staging.bedgadgets.nl` is confirmed in Openprovider and points to `46.224.190.101` with TTL 600. This IP is the existing Bulqsoft MCP host. No web-server deployment or certificate issuance has been verified. This document is an *installation runbook*, not proof of deployment.

## Non-negotiable preflight
1. Confirm `46.224.190.101` is the intended host and inventory existing applications, Nginx server names and listeners. Do not stop, replace or restart unrelated apps.
2. Confirm `staging.bedgadgets.nl` resolves to this host from the server and that **no existing server_name** uses it. Stop if it does.
3. Check existing ports 80/443 and Let's Encrypt / Certbot, and back up relevant Nginx configurations. Prefer host-based routing on existing HTTPS port 443. Do NOT expose a new public port merely because an application has a private backend listener. Keep new internal services bound to `127.0.0.1`.
4. Review and deploy code only from the reviewed commit in [PR #1](https://github.com/bulqsoft/hetzner-domain-setup/pull/1). Keep the deployment source and privileged helper owned by root, non-writable by the MCP process or webserver.
5. Set up a dedicated non-root `bulq-release` system user, and private preview Basic Auth credentials. Keep secrets in a root-owned secret store / credential manager, NEVER in Teams, GitHub, Odoo or a prompt. Restrict credential and token logs. Ensure the Nginx worker can read the protected preview password file.
6. Configure the server-specific allowlist `BULQ_ALLOWED_DNS_SUFFIXES=bedgadgets.nl`, `BULQ_ALLOWED_SERVER_IPS=46.224.190.101` and `BULQ_RELEASE_USER=bulq-release`. In shared deployments retain only explicitly approved additional domains / IPs. Specify root-owned `BULQ_SITE_ROOT`, Nginx paths, `BULQ_PREVIEW_HTPASSWD`, `BULQ_CERTBOT_EMAIL`, and dedicated approval secrets and non-reusable ledgers for the provision and release workers.
7. The low-privilege MCP service may invoke **only** the audited root-owned provisioning entrypoint through a narrowly-scoped sudo rule. Do not run the full MCP service as root or expose it as an unauthenticated endpoint. Only the verified owner-approval backend may mint 5-minute, one-use approvals bound to a plan.
8. Before provisioning, inspect the proposed plan for `project=bedgadgets`, `hostname=staging.bedgadgets.nl`, `server_ipv4=46.224.190.101`. Obtain explicit plan approval in the normal approval flow; if approval is unavailable, **stop here**. Do not mint or simulate approval as the MCP client.
9. Once approved, run the isolated provisioning entrypoint. It will create a brand-new managed folder and a preview-only Nginx vhost, validate Nginx, obtain a Let's Encrypt cert via *webroot* challenge (never Certbot's Nginx configuration plugin), enable HTTPS redirect, and grant the restricted release account ownership of the *new staging folder only*.
10. Verify `nginx -t`, `systemctl is-active nginx`, HTTP redirect (301) to HTTPS, HTTPS valid certificate for exact hostname, `401 Unauthorized` without preview password, and successful authenticated preview. Ensure Nginx's noindex header and no mixed-content warnings.
11. Verify automated Let's Encrypt renewal is enabled (Certbot timer or equivalent) and that `certbot renew --dry-run` succeeds. Do not call issuance or renewal successful until the actual host check passes.
12. Inspect release status and publish a minimal, non-sensitive `index.html` through the **non-root** release worker, with its own separately issued approval. Check revision contents, protected preview, rollback potential and no production changes. Store test evidence and commit references in the PR.
13. Confirm the pre-existing MCP service, other apps, Bulqsoft.com and mail/DNS records continue to operate normally. Report the staging URL only after a successful live HTTPS check.

## Important constraints
- The current repo is an implementation candidate. It is **not installed in the connected MCP runtime**, which currently has no generic host-install or SSH tool.
- Do not merge or deploy before the privileged boundary, file permissions, approval service and recovery paths have been reviewed.
- Existing Nginx sites and domain records must not be overwritten.
- No public website goes live and no customer billing is triggered by this staging test.
- If failure occurs after certificate issuance, Certbot may leave a valid certificate record even if the new site is rolled back. Reconcile this independently; never delete other certificates.
- This test does not yet implement AI prompt-to-site generation, Openprovider automation for arbitrary domains, Odoo payments, or production promotion. Those require separate integrations and tests.

## Verification evidence for handoff
Provide exact reviewed Git commit, server checks for DNS/Nginx/SSL/renewal, the protected URL, screenshot or redacted status of HTTP responses, and any unresolved security blockers. Never send passwords, approval tokens or API keys.

# Hetzner Domain Setup Tool

Reusable Bash script to set up a domain on a Hetzner Ubuntu/Nginx server.

This tool automates the server-side setup only.

It can:

- Check if DNS points to the expected server IP
- Create the website folder inside `/var/www`
- Copy a Coming Soon page
- Create an Nginx config
- Enable the Nginx site
- Test and reload Nginx
- Generate SSL using Certbot
- Redirect HTTP to HTTPS
- Test HTTP and HTTPS

## What this tool does not do

This tool does not create DNS records in domain providers.

You must manually create the DNS A record first.

Example:

```text
example.com → 46.224.190.101
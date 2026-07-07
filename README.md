# Hetzner Domain Setup Tool

Reusable Bash script to set up domains on a Hetzner Ubuntu/Nginx server.

This tool automates the server-side domain setup.

## What it can do

- Create website folder inside `/var/www`
- Add a Coming Soon page
- Create Nginx config
- Enable the Nginx site
- Test and reload Nginx
- Generate SSL using Certbot
- Redirect HTTP to HTTPS
- Test HTTP and HTTPS

---

## Before using this script

First, manually create the DNS A record in your domain provider.

Example:

```text
example.com → SERVER_IP
```

Then check DNS:

```bash
nslookup example.com
```

Expected result:

```text
Address: SERVER_IP
```

---

## Full server setup steps

### 1. SSH into the server

```bash
ssh your-user@SERVER_IP
```

### 2. Clone this repo on the server

```bash
cd ~
git clone https://github.com/bulqsoft/hetzner-domain-setup.git
cd hetzner-domain-setup
```

### 3. Make the script executable

```bash
chmod +x setup-domain.sh
```

### 4. Check script help

```bash
./setup-domain.sh --help
```

### 5. Run domain setup

Replace these values:

```text
example.com
/var/www/example
SERVER_IP
```

with your real domain, folder, and server IP.

```bash
sudo ./setup-domain.sh \
  --domain example.com \
  --root /var/www/example \
  --expected-ip SERVER_IP \
  --email info@bulqsoft.com \
  --force-index
```

### 6. Test the domain

```bash
curl -I https://example.com
curl -I http://example.com
```

Expected result:

```text
https://example.com → 200 OK
http://example.com  → 301 redirect to HTTPS
```

Also open in browser:

```text
https://example.com
```

---

## Example command

```bash
sudo ./setup-domain.sh \
  --domain newdomain.com \
  --root /var/www/newdomain \
  --expected-ip 123.123.123.123 \
  --email info@bulqsoft.com \
  --force-index
```

---

## Example with www alias

Only use this if both DNS records point to the same server:

```text
example.com → SERVER_IP
www.example.com → SERVER_IP
```

Then run:

```bash
sudo ./setup-domain.sh \
  --domain example.com \
  --alias www.example.com \
  --root /var/www/example \
  --expected-ip SERVER_IP \
  --email info@bulqsoft.com \
  --force-index
```

---

## Script options

```text
--domain        Main domain, example: example.com
--root          Website root folder, example: /var/www/example
--expected-ip   Check DNS points to this IP before setup
--email         Email for Let's Encrypt SSL
--alias         Extra domain, example: www.example.com
--no-ssl        Skip SSL setup
--force-index   Replace existing index.html with Coming Soon page
-h, --help      Show help
```

---

## Server requirements

The server should have:

- Ubuntu
- Nginx
- Certbot
- python3-certbot-nginx
- sudo access

Install missing packages:

```bash
sudo apt update
sudo apt install nginx certbot python3-certbot-nginx -y
```

---

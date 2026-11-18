"""Root-owned entrypoint for one approved staging provisioning request.

Install ONLY as /usr/local/sbin/bulq-staging-provision with mode 0750,
owned by root, running audited and narrowly scoped sudoers permission.
Never mount this program or its Python package from a writable web directory.
"""
import json
import os
import sys

from automation.site_engine import SiteError, provision_staging

KEYS = frozenset({"project", "hostname", "server_ipv4", "approval_token"})


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Privileged helper must run as root")
    # Read credentials from stdin, not argv, and cap request size.
    payload = sys.stdin.read(16_385)
    if len(payload) > 16_384:
        raise SystemExit("Request too large")
    try:
        request = json.loads(payload)
        if not isinstance(request, dict) or request.keys() != KEYS:
            raise SiteError("Unexpected request fields")
        if any(not isinstance(v, str) for v in request.values()):
            raise SiteError("Request parameters must be strings")
        result = provision_staging(**request)
    except (ValueError, TypeError) as exc:
        print("Provisioning refused: " + str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

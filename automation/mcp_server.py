"""MCP adapter for privileged Bulqsoft website operations.

Run over a trusted private transport only. No anonymous HTTP listener.
Production DNS changes are performed by the existing, separate DNS connector.
"""
import json
import os
import subprocess

from mcp.server.fastmcp import FastMCP

from automation.site_engine import SiteError, plan_site
from automation.site_release import plan_site_release, publish_approved_site_release, site_release_status

mcp = FastMCP("Bulqsoft Website Operations")


@mcp.tool()
def prepare_staging(project: str, hostname: str, server_ipv4: str) -> dict:
    """Prepare a non-mutating staging plan for an explicitly allowlisted host and server."""
    return plan_site(project, hostname, server_ipv4)


@mcp.tool()
def execute_approved_staging(
    project: str, hostname: str, server_ipv4: str, approval_token: str
) -> dict:
    """Create a protected new staging website ONLY with an out-of-band, one-time owner approval token.

    The token cannot be generated through MCP. Hostname must already resolve to
    the approved server. Never use this tool to modify a pre-existing website.
    """
    if os.geteuid() == 0:
        raise SiteError("The MCP server must run as a restricted, non-root account")
    request = json.dumps({"project": project, "hostname": hostname,
                          "server_ipv4": server_ipv4, "approval_token": approval_token})
    # No shell and no token in argv. The approved, root-owned entrypoint must
    # be installed separately and granted exactly one sudoers permission.
    try:
        result = subprocess.run(
            ["sudo", "-n", "/usr/local/sbin/bulq-staging-provision"],
            input=request, text=True, capture_output=True,
            check=True, timeout=240,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SiteError("Privileged staging worker failed; review restricted host logs") from exc
    return json.loads(result.stdout)




@mcp.tool()
def inspect_staging_release(project: str) -> dict:
    """Read the active staging revision before planning a change."""
    return site_release_status(project)


@mcp.tool()
def prepare_site_release(project: str, files: dict[str, str],
                         expected_revision: str) -> dict:
    """Prepare an immutable, non-mutating staging website update."""
    return plan_site_release(project, files, expected_revision)


@mcp.tool()
def execute_approved_site_release(project: str, files: dict[str, str],
                                  expected_revision: str,
                                  approval_token: str) -> dict:
    """Atomically publish a new staging revision with backend owner approval."""
    return publish_approved_site_release(project, files, expected_revision,
                                         approval_token)

if __name__ == "__main__":
    if os.geteuid() == 0:
        raise SystemExit("Refusing to run MCP server as root")
    mcp.run(transport="stdio")

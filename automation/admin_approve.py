"""Backend-only helper for minting one-time approval tokens.

This is intentionally NOT exposed as an MCP tool. Call only from a secure,
owner-authenticated approval service after explicit review of the exact plan.
"""
import argparse

from automation.site_engine import issue_approval


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-id", required=True, help="Approved plan_id (SHA-256)")
    args = parser.parse_args()
    if len(args.plan_id) != 64 or any(char not in "0123456789abcdef" for char in args.plan_id):
        parser.error("Expected a complete 64-character plan hash")
    print(issue_approval(args.plan_id))


if __name__ == "__main__":
    main()

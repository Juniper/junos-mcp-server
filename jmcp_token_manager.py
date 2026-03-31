#!/usr/bin/env python3
###
# Copyright (c) 1999-2025, Juniper Networks Inc.
#
#  All rights reserved.
#
#  License: Apache 2.0
#
#  THIS SOFTWARE IS PROVIDED BY Juniper Networks Inc. ''AS IS'' AND ANY
#  EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
#  WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#  DISCLAIMED. IN NO EVENT SHALL Juniper Networks Inc. BE LIABLE FOR ANY
#  DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
#  (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
#  LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
#  ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
#  SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
###

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

TOKENS_FILE = ".tokens"


def generate_token() -> str:
    """Generate a secure API token with jmcp_ prefix"""
    random_part = secrets.token_urlsafe(24)  # 32 chars after base64url encoding
    return f"jmcp_{random_part}"


def load_tokens() -> Dict[str, Any]:
    """Load tokens from file, return empty dict if file doesn't exist"""
    if not os.path.exists(TOKENS_FILE):
        return {}

    try:
        with open(TOKENS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_tokens(tokens: Dict[str, Any]) -> None:
    """Save tokens to file"""
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)


def generate_token_command(token_id: str, description: str = None) -> None:
    """Generate a new API token"""
    tokens = load_tokens()

    if token_id in tokens:
        print(f"Error: Token ID '{token_id}' already exists")
        sys.exit(1)

    token = generate_token()
    tokens[token_id] = {
        "token": token,
        "description": description or f"Token for {token_id}",
        "created": datetime.now(timezone.utc).isoformat(),
    }

    save_tokens(tokens)

    print(f"Generated new token:")
    print(f"  ID: {token_id}")
    print(f"  Token: {token}")
    print(f"  Description: {tokens[token_id]['description']}")
    print(f"\nSave this token securely - it won't be shown again!")


def list_tokens_command() -> None:
    """List all tokens (without showing actual token values)"""
    tokens = load_tokens()

    if not tokens:
        print("No tokens found")
        return

    print(f"{'ID':<20} {'Description':<40} {'Created':<25}")
    print("-" * 85)

    for token_id, token_data in tokens.items():
        created = token_data.get("created", "Unknown")
        description = token_data.get("description", "No description")
        token_preview = (
            token_data["token"][:12] + "..."
            if len(token_data["token"]) > 12
            else token_data["token"]
        )

        print(f"{token_id:<20} {description:<40} {created:<25}")


def revoke_token_command(token_id: str) -> None:
    """Revoke (delete) a token"""
    tokens = load_tokens()

    if token_id not in tokens:
        print(f"Error: Token ID '{token_id}' not found")
        sys.exit(1)

    del tokens[token_id]
    save_tokens(tokens)

    print(f"Token '{token_id}' has been revoked")


def show_token_command(token_id: str) -> None:
    """Show the actual token value (for recovery purposes)"""
    tokens = load_tokens()

    if token_id not in tokens:
        print(f"Error: Token ID '{token_id}' not found")
        sys.exit(1)

    token_data = tokens[token_id]
    print(f"Token ID: {token_id}")
    print(f"Token: {token_data['token']}")
    print(f"Description: {token_data.get('description', 'No description')}")
    print(f"Created: {token_data.get('created', 'Unknown')}")


def validate_token(token: str) -> bool:
    """Validate if a token exists in the tokens file"""
    tokens = load_tokens()

    for token_data in tokens.values():
        if token_data["token"] == token:
            return True

    return False


def main():
    parser = argparse.ArgumentParser(
        description="Junos MCP Server Token Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s generate --id "vscode-dev" --description "VSCode development"
  %(prog)s list
  %(prog)s show --id "vscode-dev"
  %(prog)s revoke --id "vscode-dev"
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Generate command
    generate_parser = subparsers.add_parser("generate", help="Generate a new API token")
    generate_parser.add_argument(
        "--id", required=True, help="Unique identifier for the token"
    )
    generate_parser.add_argument("--description", help="Description of the token usage")

    # List command
    list_parser = subparsers.add_parser(
        "list", help="List all tokens (without showing token values)"
    )

    # Show command
    show_parser = subparsers.add_parser("show", help="Show the actual token value")
    show_parser.add_argument("--id", required=True, help="Token ID to show")

    # Revoke command
    revoke_parser = subparsers.add_parser("revoke", help="Revoke (delete) a token")
    revoke_parser.add_argument("--id", required=True, help="Token ID to revoke")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "generate":
            generate_token_command(args.id, args.description)
        elif args.command == "list":
            list_tokens_command()
        elif args.command == "show":
            show_token_command(args.id)
        elif args.command == "revoke":
            revoke_token_command(args.id)
    except KeyboardInterrupt:
        print("\nOperation cancelled")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Provision a new embed client (API customer allowed to embed Vidya AI's UI).

Usage (run from src/, with the same env as the backend so DATABASE_URL resolves):

    python -m scripts.provision_embed_client xyz_learn "XYZ Learn" --user-type student

Prints the generated `embed_secret`. This is shown only once - store it securely.
The customer's backend uses it (with iss=<slug>, aud="vidyaai-embed") to sign
short-lived (<=5 min) HS256 JWTs for the /api/embed/session handoff endpoint.
"""

import argparse
import secrets
import sys

from utils.db import SessionLocal
from models import EmbedClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", help="Unique tenant slug, used as the JWT 'iss' claim")
    parser.add_argument("name", help="Human-readable client name")
    parser.add_argument(
        "--user-type",
        choices=["student", "professor"],
        default="student",
        help="Default user_type for embedded users when the JWT has no 'role' claim",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        existing = db.query(EmbedClient).filter(EmbedClient.slug == args.slug).first()
        if existing:
            print(f"Embed client with slug '{args.slug}' already exists.", file=sys.stderr)
            sys.exit(1)

        secret = secrets.token_urlsafe(32)
        client = EmbedClient(
            slug=args.slug,
            name=args.name,
            embed_secret=secret,
            default_user_type=args.user_type,
        )
        db.add(client)
        db.commit()

        print(f"slug={client.slug}")
        print(f"embed_secret={secret}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

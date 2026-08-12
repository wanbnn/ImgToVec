#!/usr/bin/env python3
"""Aplica todas as migrations pendentes no PostgreSQL/pgvector."""

from db_support import apply_migrations, connect


def main() -> None:
    with connect() as connection:
        apply_migrations(connection)
    print("Migrations atualizadas.")


if __name__ == "__main__":
    main()

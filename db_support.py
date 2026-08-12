#!/usr/bin/env python3
"""Configuração e migrations compartilhadas pelos scripts do projeto."""

from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.is_file():
        raise RuntimeError(f"Arquivo de ambiente não encontrado: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} precisa ser um número inteiro") from error
    if value < 1:
        raise RuntimeError(f"{name} precisa ser maior que zero")
    return value


def connect():
    try:
        import psycopg
        from psycopg import sql
    except ImportError as error:
        raise RuntimeError("Dependência ausente. Execute: python3 -m pip install -r requirements.txt") from error
    load_env()
    parameters = dict(
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ["POSTGRES_SERVER"],
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
    )
    target_database = os.environ.get("POSTGRES_DB", "img_to_vec")
    try:
        return psycopg.connect(**parameters, dbname=target_database, autocommit=False)
    except psycopg.Error as error:
        # Em algumas combinações libpq/psycopg, a falha de conexão chega como
        # OperationalError, mas mantém o SQLSTATE 3D000 (invalid_catalog_name).
        if error.sqlstate != "3D000" and "does not exist" not in str(error):
            raise

    # Sem POSTGRES_DB, a imagem Docker usa POSTGRES_USER como banco inicial.
    # Conectamos a um banco administrativo para criar o banco da aplicação.
    administrative_connection = None
    last_error = None
    for maintenance_database in ("postgres", os.environ["POSTGRES_USER"]):
        try:
            administrative_connection = psycopg.connect(
                **parameters, dbname=maintenance_database, autocommit=True
            )
            break
        except psycopg.Error as error:
            last_error = error
    if administrative_connection is None:
        raise RuntimeError(
            f"Banco '{target_database}' não existe e não foi possível acessar um banco administrativo: {last_error}"
        )
    try:
        print(f"Criando banco PostgreSQL: {target_database}")
        try:
            administrative_connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_database))
            )
        except psycopg.errors.DuplicateDatabase:
            pass
    finally:
        administrative_connection.close()
    return psycopg.connect(**parameters, dbname=target_database, autocommit=False)


def apply_migrations(connection) -> None:
    migrations_dir = ROOT / "migrations"
    with connection.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        cursor.execute("SELECT version FROM schema_migrations")
        applied = {row[0] for row in cursor.fetchall()}
        for migration in sorted(migrations_dir.glob("*.sql")):
            if migration.name in applied:
                continue
            print(f"Aplicando migration: {migration.name}")
            cursor.execute(migration.read_text(encoding="utf-8"))
            cursor.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (migration.name,))
    connection.commit()

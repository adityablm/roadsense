"""
Database connection.

Opening a new connection to Neon for every request is slow (it travels to
Singapore and back several times). A "connection pool" keeps a few connections
open and lends them out, so each request starts instantly.
"""
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

pool: ConnectionPool | None = None


def open_pool() -> ConnectionPool:
    global pool
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is empty. Put your Neon connection string in backend/.env")
    pool = ConnectionPool(
        conninfo=config.DATABASE_URL,
        min_size=1,
        max_size=5,
        kwargs={"row_factory": dict_row},     # rows come back as {"column": value} dictionaries
        check=ConnectionPool.check_connection,  # re-test a connection before lending it (Neon may have closed it)
        open=True,
    )
    return pool


def close_pool() -> None:
    if pool is not None:
        pool.close()


def connection():
    """Use as:  with db.connection() as conn:  ...
    Everything inside the block is one transaction: saved together at the end,
    or undone together if an error happens."""
    if pool is None:
        raise RuntimeError("Database pool is not open")
    return pool.connection()

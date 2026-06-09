from __future__ import annotations

import argparse
import csv
import os
import subprocess
from dataclasses import dataclass

DEFAULT_DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/typeaheadx")


@dataclass(frozen=True)
class QueryRow:
    id: int
    query: str
    historical_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query the Phase 0 storage layer")
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="PostgreSQL connection string")
    parser.add_argument("--query", help="Exact query to look up")
    parser.add_argument("--count", action="store_true", help="Print total row count")
    return parser.parse_args()


def run_psql(dsn: str, sql: str, *, variables: list[str] | None = None) -> str:
    command = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-t", "-A"]
    if variables:
        for variable in variables:
            command.extend(["-v", variable])
    command.extend(["-c", sql])
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def fetch_count(dsn: str) -> int:
    output = run_psql(dsn, "SELECT COUNT(*) FROM queries;")
    return int(output)


def fetch_query(dsn: str, query_text: str) -> QueryRow | None:
    sql = "COPY (SELECT id, query, historical_count FROM queries WHERE query = :'QUERY') TO STDOUT WITH CSV"
    completed = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-v", f"QUERY={query_text}", "-c", sql],
        check=True,
        capture_output=True,
        text=True,
    )
    output = completed.stdout.strip()
    if not output:
        return None
    row = next(csv.reader([output]))
    return QueryRow(id=int(row[0]), query=row[1], historical_count=int(row[2]))


def main() -> None:
    args = parse_args()
    if args.count:
        print(fetch_count(args.dsn))
        return
    if args.query:
        row = fetch_query(args.dsn, args.query.strip())
        if row is None:
            print("NOT FOUND")
            return
        print(f"{row.id},{row.query},{row.historical_count}")
        return
    raise SystemExit("Use --count or --query <text>")


if __name__ == "__main__":
    main()

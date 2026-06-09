from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
import psycopg
from pathlib import Path
from typing import Iterable, TextIO

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/typeaheadx")
DEFAULT_INPUT = Path(__file__).resolve().parent.parent / "data" / "processed" / "queries.csv"


def load_schema(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()


def open_input(path: str | None) -> TextIO:
    if path:
        return Path(path).open("r", encoding="utf-8", newline="")
    return sys.stdin


def iter_rows(handle: TextIO) -> Iterable[tuple[str, int]]:
    reader = csv.reader(handle)
    for row_number, row in enumerate(reader, start=1):
        if not row:
            continue
        if row_number == 1 and row[0] == "query":
            continue
        if len(row) != 2:
            raise ValueError(f"Expected 2 columns on line {row_number}, got {len(row)}")
        query = row[0].strip()
        if not query:
            continue
        try:
            historical_count = int(row[1])
        except ValueError as exc:
            raise ValueError(f"Invalid count on line {row_number}: {row[1]!r}") from exc
        yield query, historical_count


def ingest_csv(dsn: str, handle: TextIO) -> int:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False) as data_file:
        writer = csv.writer(data_file)
        row_count = 0
        for query, historical_count in iter_rows(handle):
            writer.writerow([query, historical_count])
            row_count += 1

    data_path = Path(data_file.name)

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS queries_ingest_stage;")
                cur.execute("""
                CREATE TEMP TABLE queries_ingest_stage (
                    query TEXT NOT NULL,
                    historical_count BIGINT NOT NULL
                ) ON COMMIT DROP;
                """)
                
                with open(data_path, "r", encoding="utf-8") as f:
                    with cur.copy("COPY queries_ingest_stage (query, historical_count) FROM STDIN WITH (FORMAT CSV)") as copy:
                        while data := f.read(8192):
                            copy.write(data)
                
                cur.execute("""
                INSERT INTO queries (query, historical_count)
                SELECT query, historical_count
                FROM queries_ingest_stage
                ON CONFLICT (query)
                DO UPDATE SET historical_count = queries.historical_count + EXCLUDED.historical_count;
                """)
            conn.commit()
    finally:
        data_path.unlink(missing_ok=True)

    return row_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load query,count rows into PostgreSQL")
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="PostgreSQL connection string")
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT),
        help="Path to a CSV file with rows in the form query,count. Defaults to data/processed/queries.csv.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_handle = open_input(args.input)
    try:
        load_schema(args.dsn)
        loaded_rows = ingest_csv(args.dsn, input_handle)
    finally:
        if input_handle is not sys.stdin:
            input_handle.close()
    print(f"Loaded {loaded_rows} input rows")


if __name__ == "__main__":
    main()

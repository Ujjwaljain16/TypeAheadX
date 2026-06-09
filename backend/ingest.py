from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, TextIO

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/typeaheadx")
DEFAULT_INPUT = Path(__file__).resolve().parent.parent / "data" / "processed" / "queries.csv"


def run_psql(dsn: str, sql_path: Path) -> None:
    subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-f", str(sql_path)],
        check=True,
    )


def load_schema(dsn: str) -> None:
    run_psql(dsn, SCHEMA_PATH)


def open_input(path: str | None) -> TextIO:
    if path:
        return Path(path).open("r", encoding="utf-8", newline="")
    return sys.stdin


def iter_rows(handle: TextIO) -> Iterable[tuple[str, int]]:
    reader = csv.reader(handle)
    for row_number, row in enumerate(reader, start=1):
        if not row:
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
    script_content = f"""
DROP TABLE IF EXISTS queries_ingest_stage;
CREATE TEMP TABLE queries_ingest_stage (
    query TEXT NOT NULL,
    historical_count BIGINT NOT NULL
) ON COMMIT DROP;
\copy queries_ingest_stage (query, historical_count) FROM '{data_path.as_posix()}' WITH (FORMAT CSV)
INSERT INTO queries (query, historical_count)
SELECT query, historical_count
FROM queries_ingest_stage
ON CONFLICT (query)
DO UPDATE SET historical_count = queries.historical_count + EXCLUDED.historical_count;
"""

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".sql", delete=False) as script_file:
        script_file.write(script_content)
        script_path = Path(script_file.name)

    try:
        run_psql(dsn, script_path)
    finally:
        data_path.unlink(missing_ok=True)
        script_path.unlink(missing_ok=True)

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

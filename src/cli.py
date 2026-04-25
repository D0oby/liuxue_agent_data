from __future__ import annotations

import argparse
from pathlib import Path

from src.config import load_settings
from src.db import apply_migrations, connect
from src.extract.excel_reader import read_excel_rows
from src.load.upsert_admission_requirements import replace_admission_requirement
from src.load.upsert_courses import build_source_row_hash, build_course_record, upsert_course
from src.load.upsert_intakes import replace_intakes


def import_excel_to_postgres(file_path: str, migrate_first: bool = False) -> None:
    settings = load_settings()
    rows_payload = read_excel_rows(file_path)
    migrations_dir = Path(__file__).resolve().parents[1] / "migrations"

    with connect(settings) as conn:
        with conn.transaction():
            if migrate_first:
                apply_migrations(conn, migrations_dir)

            for raw_row in rows_payload.rows:
                source_row_hash = build_source_row_hash(
                    row=raw_row.values,
                    source_file_name=rows_payload.source_file_name,
                    source_sheet_name=rows_payload.source_sheet_name,
                    source_row_number=raw_row.source_row_number,
                )
                course_record = build_course_record(
                    raw_row=raw_row,
                    source_file_name=rows_payload.source_file_name,
                    source_sheet_name=rows_payload.source_sheet_name,
                    source_row_hash=source_row_hash,
                )
                course_id = upsert_course(conn, course_record)
                replace_intakes(conn, course_id, course_record.intakes)
                replace_admission_requirement(
                    conn,
                    course_id,
                    course_record.admission_requirement,
                )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USYD postgraduate Excel importer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate_parser = subparsers.add_parser("migrate", help="Apply SQL migrations")
    migrate_parser.set_defaults(command="migrate")

    import_parser = subparsers.add_parser("import-excel", help="Import an Excel file")
    import_parser.add_argument("--file", required=True, help="Path to the source .xlsx file")
    import_parser.add_argument(
        "--migrate-first",
        action="store_true",
        help="Run SQL migrations before importing",
    )
    import_parser.set_defaults(command="import-excel")

    crawl_parser = subparsers.add_parser(
        "crawl-admissions",
        help="Crawl the University of Sydney website and fill admissions details back into PostgreSQL",
    )
    crawl_parser.add_argument("--limit", type=int, default=20, help="Maximum number of courses to crawl")
    crawl_parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Crawl courses even when they already have a usyd_web_crawl admissions snapshot",
    )
    crawl_parser.add_argument(
        "--retry-dlq",
        action="store_true",
        help="Retry courses that are currently represented only in the admissions DLQ",
    )
    crawl_parser.add_argument(
        "--dlq-file",
        default="var/usyd_admissions_dlq.jsonl",
        help="Path to the local JSONL DLQ output",
    )
    crawl_parser.set_defaults(command="crawl-admissions")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "migrate":
        settings = load_settings()
        migrations_dir = Path(__file__).resolve().parents[1] / "migrations"
        with connect(settings) as conn:
            with conn.transaction():
                apply_migrations(conn, migrations_dir)
        print("Migrations applied successfully.")
        return

    if args.command == "import-excel":
        import_excel_to_postgres(args.file, migrate_first=args.migrate_first)
        print(f"Imported {args.file} successfully.")
        return

    if args.command == "crawl-admissions":
        from src.crawl.runner import crawl_admissions

        settings = load_settings()
        with connect(settings) as conn:
            with conn.transaction():
                crawl_admissions(
                    conn,
                    limit=args.limit,
                    only_missing=not args.include_existing,
                    dlq_path=args.dlq_file,
                    retry_dlq=args.retry_dlq,
                )
        print(f"Crawled up to {args.limit} courses successfully.")
        return

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()

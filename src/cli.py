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

    vector_parser = subparsers.add_parser(
        "vectorize-admissions",
        help="Chunk crawled admissions text, embed it, and store it in ChromaDB",
    )
    vector_parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of current admission records to vectorize",
    )
    vector_parser.add_argument(
        "--source",
        default="usyd_web_crawl",
        help="Admission requirement_source to vectorize; use 'all' to include every source",
    )
    vector_parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild chunks and embeddings even when matching vectors already exist",
    )
    vector_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build chunks and print counts without calling the embedding API or writing vectors",
    )
    vector_parser.add_argument("--max-chars", type=int, default=1200, help="Maximum characters per text chunk")
    vector_parser.add_argument(
        "--overlap-chars",
        type=int,
        default=160,
        help="Character overlap between adjacent chunks",
    )
    vector_parser.set_defaults(command="vectorize-admissions")

    search_parser = subparsers.add_parser(
        "search-admissions",
        help="Run a semantic search over vectorized admissions chunks",
    )
    search_parser.add_argument("query", help="Natural-language admissions query")
    search_parser.add_argument("--top-k", type=int, default=5, help="Number of matching chunks to print")
    search_parser.set_defaults(command="search-admissions")
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

    if args.command == "vectorize-admissions":
        from src.vector_store.embeddings import OpenAIEmbeddingClient
        from src.vector_store.runner import vectorize_admissions
        from src.vector_store.storage import ChromaVectorStore

        settings = load_settings()
        vector_store = ChromaVectorStore.from_settings(settings)
        embedding_client = None
        if not args.dry_run:
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required to create embeddings.")
            embedding_client = OpenAIEmbeddingClient(
                api_key=settings.openai_api_key,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
                base_url=settings.openai_base_url,
                api_mode=settings.embedding_api_mode,
                max_workers=settings.embedding_max_workers,
            )

        source = None if args.source == "all" else args.source
        with connect(settings) as conn:
            stats = vectorize_admissions(
                conn,
                vector_store=vector_store,
                embedding_client=embedding_client,
                embedding_model=settings.embedding_model,
                source=source,
                limit=args.limit,
                batch_size=settings.embedding_batch_size,
                force=args.force,
                dry_run=args.dry_run,
                max_chars=args.max_chars,
                overlap_chars=args.overlap_chars,
            )
            if not args.dry_run:
                conn.commit()
        print(
            "Vectorized admissions: "
            f"{stats.records_vectorized}/{stats.records_seen} records, "
            f"{stats.chunks_embedded or stats.chunks_built} chunks, "
            f"{stats.records_skipped} skipped."
        )
        return

    if args.command == "search-admissions":
        from src.vector_store.embeddings import OpenAIEmbeddingClient
        from src.vector_store.runner import search_admissions
        from src.vector_store.storage import ChromaVectorStore

        settings = load_settings()
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required to embed the search query.")
        vector_store = ChromaVectorStore.from_settings(settings)

        embedding_client = OpenAIEmbeddingClient(
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            base_url=settings.openai_base_url,
            api_mode=settings.embedding_api_mode,
            max_workers=settings.embedding_max_workers,
        )
        results = search_admissions(
            vector_store=vector_store,
            embedding_client=embedding_client,
            embedding_model=settings.embedding_model,
            query=args.query,
            top_k=args.top_k,
        )
        for index, result in enumerate(results, start=1):
            print(
                f"{index}. {result.course_name} ({result.cricos}) "
                f"[{result.chunk_kind}] score={result.similarity:.3f}"
            )
            if result.source_url:
                print(f"   Source: {result.source_url}")
            print(f"   {result.content[:500]}")
        return

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()

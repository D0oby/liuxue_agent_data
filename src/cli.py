from __future__ import annotations

import argparse
import os
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

    feature_parser = subparsers.add_parser(
        "generate-course-features",
        help="Generate rule-based course feature profiles into courses.course_features",
    )
    feature_parser.add_argument("--limit", type=int, help="Maximum number of courses to process")
    feature_parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Regenerate courses that already have course_features; manual overrides are preserved",
    )
    feature_parser.add_argument("--dry-run", action="store_true", help="Print counts without writing")
    feature_parser.set_defaults(command="generate-course-features")

    audit_parser = subparsers.add_parser(
        "audit-course-features",
        help="Audit stored course feature profiles and print deterministic findings",
    )
    audit_parser.add_argument("--limit", type=int, help="Maximum number of courses to inspect")
    audit_parser.set_defaults(command="audit-course-features")

    e2e_parser = subparsers.add_parser(
        "e2e-regression",
        help="Run the hermetic USYD data-to-dashboard E2E regression suite",
    )
    e2e_parser.add_argument(
        "--database-url",
        help="Explicit isolated E2E PostgreSQL URL. Defaults to E2E_DATABASE_URL; never falls back to DATABASE_URL.",
    )
    e2e_parser.add_argument(
        "--artifacts-dir",
        default="var/e2e_artifacts",
        help="Directory for E2E run summaries, logs, screenshots, and debug artifacts.",
    )
    e2e_parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep temporary fixture/vector state for debugging instead of cleaning it after the run.",
    )
    e2e_parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Playwright in headed mode for local debugging. The default is headless.",
    )
    e2e_parser.add_argument(
        "--skip-dashboard",
        action="store_true",
        help="Skip the Streamlit/Playwright stage when browser dependencies are unavailable.",
    )
    e2e_parser.add_argument(
        "--skip-api-smoke",
        action="store_true",
        help="Skip the thin FastAPI schema smoke stage.",
    )
    e2e_parser.set_defaults(command="e2e-regression")
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

    if args.command == "generate-course-features":
        from src.recommendation.course_features import generate_course_features
        from src.recommendation.feature_repository import CourseFeatureRepository

        settings = load_settings()
        repository = CourseFeatureRepository()
        generated_count = 0
        with connect(settings) as conn:
            course_ids = repository.fetch_course_ids_for_generation(
                conn,
                limit=args.limit,
                only_missing=not args.include_existing,
            )
            for course_id in course_ids:
                record = repository.fetch_course(conn, course_id=course_id)
                if record is None:
                    continue
                profile = generate_course_features(record.source, manual_override=record.manual_overrides)
                generated_count += 1
                if not args.dry_run:
                    repository.save_course_features(
                        conn,
                        course_id=course_id,
                        course_features=profile,
                        manual_overrides=record.manual_overrides,
                    )
            if not args.dry_run:
                conn.commit()
        action = "Generated" if not args.dry_run else "Dry-run generated"
        print(f"{action} {generated_count}/{len(course_ids)} course feature profiles.")
        return

    if args.command == "audit-course-features":
        from src.recommendation.course_features import audit_course_feature_profiles
        from src.recommendation.feature_repository import CourseFeatureRepository

        settings = load_settings()
        repository = CourseFeatureRepository()
        with connect(settings) as conn:
            findings = audit_course_feature_profiles(
                repository.fetch_feature_audit_rows(conn, limit=args.limit)
            )
        if not findings:
            print("No course feature profile audit findings.")
            return
        for finding in findings:
            print(f"{finding.course_id}\t{finding.code}\t{finding.course_name}\t{finding.message}")
        return

    if args.command == "e2e-regression":
        from src.e2e_regression import E2ERunOptions, run_e2e_regression

        result = run_e2e_regression(
            E2ERunOptions(
                database_url=args.database_url or os.getenv("E2E_DATABASE_URL"),
                normal_database_url=os.getenv("DATABASE_URL"),
                artifacts_dir=Path(args.artifacts_dir),
                keep_artifacts=args.keep_artifacts,
                headed=args.headed,
                skip_dashboard=args.skip_dashboard,
                run_api_smoke=not args.skip_api_smoke,
            )
        )
        for stage in result.stages:
            print(f"{stage.status.upper()}\t{stage.name}")
        print(f"E2E summary: {result.run_artifacts_dir / 'summary.json'}")
        if not result.success:
            raise SystemExit(1)
        return

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()

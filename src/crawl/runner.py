from __future__ import annotations

from pathlib import Path

from scrapy.crawler import CrawlerProcess

from src.crawl.dlq import append_dlq_record, insert_dlq_record
from src.crawl.seed_loader import fetch_course_seeds
from src.crawl.spider import UsydAdmissionsSpider
from src.crawl.storage import upsert_crawled_admission_requirement


def crawl_admissions(
    conn,
    limit: int = 20,
    only_missing: bool = True,
    dlq_path: str | None = None,
    retry_dlq: bool = False,
) -> None:
    seeds = fetch_course_seeds(conn, limit=limit, only_missing=only_missing, retry_dlq=retry_dlq)
    if not seeds:
        print("No matching courses found for admissions crawling.")
        return

    results: list[dict] = []
    process = CrawlerProcess(settings={"LOG_LEVEL": "ERROR"})
    process.crawl(UsydAdmissionsSpider, seeds=[seed.__dict__ for seed in seeds], results=results)
    process.start()

    output_path = Path(dlq_path or "var/usyd_admissions_dlq.jsonl")
    for result in results:
        if result["status"] == "ok":
            upsert_crawled_admission_requirement(conn, result["payload"])
            continue
        record = {
            "cricos": result["seed"]["cricos"],
            "course_name": result["seed"]["course_name"],
            "source_url": result.get("source_url") or result["seed"].get("source_url"),
            "stage": result["stage"],
            "error_code": result["error_code"],
            "error_message": result["error_message"],
            "raw_payload_json": result.get("raw_payload_json", {}),
            "raw_html_excerpt": result.get("raw_html_excerpt"),
            "source_context_json": {
                "seed": result["seed"],
                "status": result["status"],
            },
            "retryable": result["error_code"] not in {"DISCOVERY_NO_MATCH", "VALIDATION_ENUM_FAIL"},
        }
        append_dlq_record(output_path, record)
        insert_dlq_record(conn, record)

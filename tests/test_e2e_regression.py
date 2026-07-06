from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from src.e2e_regression import (
    DeterministicEmbeddingClient,
    E2E_FIXTURE_COURSES,
    E2E_STAGE_SEQUENCE,
    E2EStageError,
    E2ERunOptions,
    write_representative_fixture_excel,
    run_e2e_regression,
)
from src.extract.excel_reader import read_excel_rows


class E2ERegressionHarnessTests(unittest.TestCase):
    def test_harness_refuses_to_run_without_explicit_e2e_database_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_e2e_regression(
                E2ERunOptions(
                    database_url=None,
                    normal_database_url="postgresql://localhost/dev",
                    artifacts_dir=Path(tmpdir),
                )
            )

            self.assertFalse(result.success)
            self.assertEqual(result.failed_stage, "database_guard")
            self.assertTrue((result.run_artifacts_dir / "summary.json").exists())

    def test_harness_runs_regression_stages_in_order_with_explicit_e2e_database(self) -> None:
        environment = RecordingEnvironment()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_e2e_regression(
                E2ERunOptions(
                    database_url="postgresql://localhost/usyd_e2e",
                    normal_database_url="postgresql://localhost/dev",
                    artifacts_dir=Path(tmpdir),
                ),
                environment=environment,
            )

            self.assertTrue(result.success)
            self.assertEqual(environment.stage_names, E2E_STAGE_SEQUENCE[1:])
            self.assertEqual([stage.name for stage in result.stages], E2E_STAGE_SEQUENCE)

    def test_harness_writes_failed_stage_diagnostics_to_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_e2e_regression(
                E2ERunOptions(
                    database_url="postgresql://localhost/usyd_e2e",
                    normal_database_url="postgresql://localhost/dev",
                    artifacts_dir=Path(tmpdir),
                ),
                environment=FailingEnvironment("dashboard_playwright"),
            )

            summary = json.loads((result.run_artifacts_dir / "summary.json").read_text(encoding="utf-8"))

            self.assertFalse(result.success)
            self.assertEqual(result.failed_stage, "dashboard_playwright")
            self.assertEqual(summary["failed_stage"], "dashboard_playwright")
            self.assertIn("dashboard_failure.png", json.dumps(summary))

    def test_harness_reports_unexpected_stage_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_e2e_regression(
                E2ERunOptions(
                    database_url="postgresql://localhost/usyd_e2e",
                    normal_database_url="postgresql://localhost/dev",
                    artifacts_dir=Path(tmpdir),
                ),
                environment=ExplodingEnvironment(),
            )

            self.assertFalse(result.success)
            self.assertEqual(result.failed_stage, "migrations")
            self.assertTrue((result.run_artifacts_dir / "summary.json").exists())

    def test_representative_fixture_excel_uses_existing_excel_reader_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_path = Path(tmpdir) / "fixture.xlsx"

            write_representative_fixture_excel(fixture_path)
            payload = read_excel_rows(str(fixture_path))

            self.assertEqual(len(payload.rows), len(E2E_FIXTURE_COURSES))
            course_names = {row.values["Course Name"] for row in payload.rows}
            self.assertIn("Master of Data Science", course_names)
            self.assertIn("Master of Business Analytics", course_names)

    def test_deterministic_embedding_is_local_and_repeatable(self) -> None:
        client = DeterministicEmbeddingClient()

        first = client.embed_texts(["portfolio design application"])[0]
        second = client.embed_texts(["portfolio design application"])[0]
        unrelated = client.embed_texts(["business analytics statistics"])[0]

        self.assertEqual(first, second)
        self.assertNotEqual(first, unrelated)
        self.assertGreater(sum(first), 0)


class RecordingEnvironment:
    def __init__(self) -> None:
        self.stage_names: list[str] = []

    def run_stage(self, stage_name: str, context) -> dict[str, object]:
        self.stage_names.append(stage_name)
        return {"observed": stage_name, "headed": context.options.headed}


class FailingEnvironment(RecordingEnvironment):
    def __init__(self, failed_stage: str) -> None:
        super().__init__()
        self.failed_stage = failed_stage

    def run_stage(self, stage_name: str, context) -> dict[str, object]:
        if stage_name == self.failed_stage:
            raise E2EStageError(
                stage_name,
                "intentional failure",
                details={"screenshot": str(context.run_artifacts_dir / "dashboard_failure.png")},
            )
        return super().run_stage(stage_name, context)


class ExplodingEnvironment:
    def run_stage(self, stage_name: str, context) -> dict[str, object]:
        raise RuntimeError("unexpected boom")


if __name__ == "__main__":
    unittest.main()

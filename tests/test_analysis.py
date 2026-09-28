import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import analysis


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.config = analysis.Config(
            start=pd.Timestamp("2015-01-01"),
            end=pd.Timestamp("2026-08-31"),
            source="sample",
        )

    def test_last_complete_month_is_not_current_partial_month(self):
        result = analysis.last_complete_month_end(pd.Timestamp("2026-09-20").date())
        self.assertEqual(result, pd.Timestamp("2026-08-31"))

    def test_sample_pipeline_has_at_least_100_complete_months(self):
        levels, auxiliary, _ = analysis.collect_sample_data(self.config)
        # 샘플 검사가 제출용 실데이터 CSV를 덮어쓰지 않도록 임시 폴더만 사용한다.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed_dir = root / "processed"
            output_dir = root / "outputs"
            processed_dir.mkdir()
            output_dir.mkdir()
            with (
                patch.object(analysis, "PROCESSED_DIR", processed_dir),
                patch.object(analysis, "OUTPUT_DIR", output_dir),
            ):
                monthly, _ = analysis.process_monthly(levels, self.config)
                quarterly = analysis.process_quarterly(auxiliary, monthly)
        self.assertGreaterEqual(len(monthly), 100)
        self.assertFalse(quarterly.empty)
        self.assertFalse(monthly.index.duplicated().any())

    def test_outlier_flag_does_not_delete_observation(self):
        series = pd.Series([0.0] * 20 + [50.0])
        flags = analysis.robust_outlier_flags(series)
        self.assertEqual(len(flags), len(series))

    def test_header_only_manual_insurance_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            manual_dir = Path(directory)
            (manual_dir / "kospi_insurance.csv").write_text("date,close\n", encoding="utf-8")
            with patch.object(analysis, "MANUAL_DIR", manual_dir):
                self.assertIsNone(analysis.load_manual_insurance_index())

    def test_finstate_column_layout_and_future_rows(self):
        frame = pd.DataFrame(
            {"영업이익": [100, 110, 120, 130, 999]},
            index=pd.to_datetime(
                ["2025-03-01", "2025-06-01", "2025-09-01", "2025-12-01", "2026-03-01"]
            ),
        )
        result = analysis.parse_finstate_operating_profit(frame, end=pd.Timestamp("2025-12-31"))
        self.assertEqual(len(result), 4)
        self.assertEqual(result.index.max(), pd.Timestamp("2025-12-31"))
        self.assertNotIn(999, result.tolist())


if __name__ == "__main__":
    unittest.main()

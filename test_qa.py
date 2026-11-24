import unittest

from qa import audit, sample


class RecordingAuditTests(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(audit(sample("clean"))["status"], "pass")

    def test_injected_faults(self):
        streams = audit(sample("mixed"))["streams"]
        self.assertEqual(streams["tactile"]["issues"][0]["locations"], [
            {"from_ms": 2590, "to_ms": 2810, "duration_ms": 220}
        ])
        emg = streams["emg"]
        self.assertEqual(emg["metrics"]["offset_ms"], 84)
        self.assertEqual(emg["metrics"]["drift_ms"], 40)
        self.assertEqual([item["code"] for item in emg["issues"]],
                         ["clock_offset", "clock_drift"])

    def test_missing_stream(self):
        self.assertEqual(audit(sample("missing"))["streams"]["emg"]["issues"],
                         [{"code": "missing_stream"}])

    def test_missing_reference(self):
        results = audit(sample("markers"))["streams"]
        self.assertEqual(results["video"]["issues"], [{"code": "invalid_sync_markers"}])
        self.assertEqual(results["emg"]["issues"], [{"code": "video_reference_unavailable"}])

    def test_timestamp_order(self):
        issues = audit(sample("order"))["streams"]["tactile"]["issues"]
        self.assertEqual(issues, [{"code": "timestamp_order", "count": 1}])

    def test_thresholds(self):
        self.assertEqual(audit(sample("drift"), offset_ms=90, drift_ms=45)["status"], "pass")

    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            audit({"streams": []})
        recording = sample("clean")
        recording["streams"]["emg"]["timestamps_ms"][2] = float("nan")
        self.assertEqual(audit(recording)["streams"]["emg"]["issues"],
                         [{"code": "invalid_timestamps"}])


if __name__ == "__main__":
    unittest.main()

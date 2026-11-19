import calendar
import unittest
from urllib.parse import urlsplit
from unittest import mock

import check_hosts
from check_hosts import Result, evaluate


class EvaluateTests(unittest.TestCase):
    def test_healthy(self):
        self.assertEqual(evaluate(200, 60, None, 14), [])

    def test_redirect_is_healthy(self):
        self.assertEqual(evaluate(301, 60, None, 14), [])

    def test_client_and_server_errors_fail(self):
        for status in (400, 404, 500, 503, 199):
            with self.subTest(status=status):
                self.assertEqual(evaluate(status, 60, None, 14),
                                 [f"HTTP status {status}"])

    def test_certificate_inside_threshold_fails(self):
        problems = evaluate(200, 13.9, None, 14)
        self.assertEqual(len(problems), 1)
        self.assertIn("certificate expires in 13.9 days", problems[0])

    def test_certificate_at_threshold_passes(self):
        self.assertEqual(evaluate(200, 14.0, None, 14), [])

    def test_forced_threshold_fails_every_host(self):
        # The alert proof uses a 400-day limit; real certificates last 90.
        self.assertTrue(evaluate(200, 89, None, 400))

    def test_expected_gate_answer_is_healthy(self):
        gate = (401, "<title>Riddle</title>")
        self.assertEqual(evaluate(401, 60, None, 14, gate,
                                  "<html><title>Riddle</title>"), [])

    def test_expected_gate_needs_its_marker(self):
        gate = (401, "<title>Riddle</title>")
        problems = evaluate(401, 60, None, 14, gate, "Unauthorized")
        self.assertEqual(len(problems), 1)
        self.assertIn("missing", problems[0])

    def test_expected_gate_rejects_other_statuses(self):
        gate = (401, "<title>Riddle</title>")
        for status in (200, 500):
            with self.subTest(status=status):
                self.assertEqual(
                    evaluate(status, 60, None, 14, gate, "<title>Riddle</title>"),
                    [f"HTTP status {status} (expected 401)"])

    def test_tls_error_reported_once(self):
        self.assertEqual(evaluate(None, None, "TLS connection failed: x", 14),
                         ["TLS connection failed: x"])

    def test_missing_response_without_error(self):
        self.assertEqual(evaluate(None, 60, None, 14), ["no HTTP response"])


class CertDaysTests(unittest.TestCase):
    def test_days_left(self):
        now = calendar.timegm((2026, 11, 19, 0, 0, 0))
        days = check_hosts.cert_days_left("Dec 19 00:00:00 2026 GMT", now)
        self.assertAlmostEqual(days, 30.0, places=3)


class RetryTests(unittest.TestCase):
    def test_retries_once_then_reports_second_result(self):
        bad = Result("h", problems=["HTTP status 503"])
        good = Result("h", status=200, days_left=60, problems=[])
        with mock.patch.object(check_hosts, "probe", side_effect=[bad, good]) as p:
            result = check_hosts.check("h", 14, pause=0)
        self.assertTrue(result.ok)
        self.assertEqual(p.call_count, 2)

    def test_no_retry_when_healthy(self):
        good = Result("h", status=200, days_left=60, problems=[])
        with mock.patch.object(check_hosts, "probe", return_value=good) as p:
            check_hosts.check("h", 14, pause=0)
        self.assertEqual(p.call_count, 1)


class MainTests(unittest.TestCase):
    def test_exit_code_and_summary(self):
        results = {
            "a": Result("a", status=200, days_left=60, problems=[]),
            "b": Result("b", status=502, days_left=60, problems=["HTTP status 502"]),
        }
        with mock.patch.object(check_hosts, "check",
                               side_effect=lambda h, d: results[h]), \
             mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch("builtins.print") as printed:
            code = check_hosts.main(["a", "b"])
        self.assertEqual(code, 1)
        output = "\n".join(str(c.args[0]) for c in printed.call_args_list)
        self.assertIn("1 of 2 checks healthy", output)
        self.assertIn("| b | **FAIL** | 502 |", output)
        self.assertIn("::error title=b::HTTP status 502", output)

    def test_url_list_covers_seven_distinct_https_hosts(self):
        hosts = {urlsplit(u).hostname for u in check_hosts.URLS}
        self.assertEqual(len(check_hosts.URLS), 7)
        self.assertEqual(len(hosts), 7)
        self.assertTrue(all(u.startswith("https://") for u in check_hosts.URLS))


if __name__ == "__main__":
    unittest.main()

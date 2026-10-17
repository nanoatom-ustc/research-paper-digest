import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock, patch

import requests

from crossref_fetcher import CrossrefFetcher, CrossrefFetchError


def response(status=200, retry_after=None, items=None):
    result = requests.Response()
    result.status_code = status
    result._content_consumed = True
    result._content = b'{}'
    result.json = lambda: {"message": {"items": items or []}}
    if retry_after:
        result.headers["Retry-After"] = retry_after
    return result


class CrossrefRetryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.waits = []
        CrossrefFetcher._last_request = None
        CrossrefFetcher._cooldown_until = 0.0
        for target, value in (("crossref_fetcher.time.monotonic", lambda: self.now),
                              ("crossref_fetcher.time.sleep", self.advance)):
            mocked = patch(target, side_effect=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.addCleanup(setattr, CrossrefFetcher, "_last_request", None)
        self.addCleanup(setattr, CrossrefFetcher, "_cooldown_until", 0.0)
        self.session = Mock()
        self.fetcher = CrossrefFetcher(session=self.session)
        self.fetcher.keywords = ["quantum"]

    def advance(self, seconds):
        self.waits.append(seconds)
        self.now += seconds

    def test_429_recovers_and_respects_retry_after(self):
        self.session.get.side_effect = [response(429, "75"), response()]
        self.assertEqual(self.fetcher.fetch_recent_papers(), [])
        self.assertEqual(self.waits, [75])

    def test_timeouts_and_503_recover(self):
        self.session.get.side_effect = [requests.Timeout(), response(503), response()]
        self.assertEqual(self.fetcher.fetch_recent_papers(), [])
        self.assertEqual(self.waits, [30, 60])

    def test_exhaustion_is_failure_not_empty_success(self):
        self.session.get.side_effect = [response(429) for _ in range(4)]
        with self.assertRaises(CrossrefFetchError) as caught:
            self.fetcher.fetch_recent_papers()
        self.assertEqual(caught.exception.papers, [])
        self.assertEqual(self.session.get.call_count, 4)
        self.assertEqual(self.waits, [30, 60, 120])

    def test_long_retry_after_is_not_shortened(self):
        self.session.get.return_value = response(429, "301")
        with self.assertRaises(CrossrefFetchError):
            self.fetcher.fetch_recent_papers()
        self.assertEqual(self.session.get.call_count, 1)
        self.assertEqual(self.waits, [])

    def test_retry_budget_shared_by_keywords_and_resets_next_run(self):
        self.fetcher.keywords = ["quantum", "atom"]
        self.session.get.side_effect = [response(429, "200"), response(), response(429, "200")]
        with self.assertRaises(CrossrefFetchError):
            self.fetcher.fetch_recent_papers()
        self.assertEqual(self.session.get.call_count, 3)
        self.assertEqual(self.fetcher._retry_wait, 200)
        self.session.get.side_effect = [response(429, "30"), response(), response()]
        self.assertEqual(self.fetcher.fetch_recent_papers(), [])
        self.assertEqual(self.fetcher._retry_wait, 230)

    def test_long_cooldown_blocks_other_publishers_too(self):
        self.session.get.return_value = response(429, "301")
        with self.assertRaises(CrossrefFetchError):
            self.fetcher.fetch_recent_papers()
        other = CrossrefFetcher(session=self.session)
        other.keywords = ["atom"]
        with self.assertRaises(CrossrefFetchError):
            other.fetch_recent_papers()
        self.assertEqual(self.session.get.call_count, 1)

    def test_pacing_shared_across_publishers(self):
        self.session.get.return_value = response()
        self.fetcher.fetch_recent_papers()
        other = CrossrefFetcher(session=self.session)
        other.keywords = ["atom"]
        other.fetch_recent_papers()
        self.assertEqual(self.waits, [1])

    def test_permanent_http_error_is_not_retried(self):
        self.session.get.return_value = response(400)
        with self.assertRaises(CrossrefFetchError):
            self.fetcher.fetch_recent_papers()
        self.assertEqual(self.session.get.call_count, 1)

    def test_partial_results_survive_failed_keyword(self):
        self.fetcher.keywords = ["quantum", "atom"]
        item = {"DOI": "10.1234/test", "title": ["Quantum atom experiment"]}
        self.session.get.side_effect = [response(items=[item]), response(400)]
        with self.assertRaises(CrossrefFetchError) as caught:
            self.fetcher.fetch_recent_papers()
        self.assertEqual(caught.exception.papers[0]["doi"], "10.1234/test")
        self.session.get.side_effect = None
        self.session.get.return_value = response()
        self.assertEqual(self.fetcher.fetch_recent_papers(), [])

    def test_malformed_payload_is_failure(self):
        bad = response()
        bad.json = lambda: {"message": {}}
        self.session.get.return_value = bad
        with self.assertRaises(CrossrefFetchError):
            self.fetcher.fetch_recent_papers()

    def test_retry_after_date_and_invalid_values(self):
        future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=90))
        self.assertGreater(self.fetcher._retry_after(future), 88)
        for value in (None, "", "bad", "-1", "NaN"):
            self.assertEqual(self.fetcher._retry_after(value), 0)

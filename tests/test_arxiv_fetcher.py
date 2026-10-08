import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests

from arxiv_fetcher import ArxivFetcher, ArxivFetchError, _ArxivSession


EMPTY_FEED = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"
 xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
 <opensearch:totalResults>0</opensearch:totalResults></feed>'''
PAPER_FEED = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"
 xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
 xmlns:arxiv="http://arxiv.org/schemas/atom">
 <opensearch:totalResults>1</opensearch:totalResults>
 <entry><id>http://arxiv.org/abs/2610.00001v1</id><title>Scalable atom arrays</title>
 <published>2026-10-07T00:00:00Z</published><updated>2026-10-07T00:00:00Z</updated>
 <summary>Neutral atom arrays for quantum computing.</summary><author><name>A. Author</name></author>
 <arxiv:primary_category term="quant-ph"/><category term="quant-ph"/>
 <link href="https://arxiv.org/pdf/2610.00001" title="pdf" rel="related" type="application/pdf"/>
 </entry></feed>'''


def response(status, retry_after=None, content=EMPTY_FEED):
    result = requests.Response()
    result.status_code = status
    result._content = content
    result._content_consumed = True
    if retry_after is not None:
        result.headers['Retry-After'] = retry_after
    return result


class ArxivRetryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.waits = []
        self.monotonic = patch('arxiv_fetcher.time.monotonic', side_effect=lambda: self.now)
        self.sleep = patch('arxiv_fetcher.time.sleep', side_effect=self.advance)
        self.monotonic.start()
        self.sleep.start()
        self.addCleanup(self.monotonic.stop)
        self.addCleanup(self.sleep.stop)

    def advance(self, delay):
        self.waits.append(delay)
        self.now += delay

    @patch('requests.Session.get')
    def test_429_then_success_respects_retry_after(self, get):
        get.side_effect = [response(429, '75'), response(200)]
        self.assertEqual(_ArxivSession().get('https://example.test').status_code, 200)
        self.assertEqual(self.waits, [75])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.kwargs['timeout'], (10, 30))

    @patch('requests.Session.get')
    def test_429_exhaustion_bounded_exponential_backoff(self, get):
        get.side_effect = [response(429) for _ in range(4)]
        with self.assertRaises(requests.HTTPError):
            _ArxivSession().get('https://example.test')
        self.assertEqual(get.call_count, 4)
        self.assertEqual(self.waits, [30, 60, 120])

    @patch('requests.Session.get')
    def test_long_retry_after_fails_without_retrying_early(self, get):
        get.return_value = response(429, '301')
        with self.assertRaises(ArxivFetchError):
            _ArxivSession().get('https://example.test')
        self.assertEqual(get.call_count, 1)
        self.assertEqual(self.waits, [])

    @patch('requests.Session.get')
    def test_cumulative_server_wait_budget(self, get):
        get.side_effect = [response(429, '200'), response(429, '200')]
        with self.assertRaises(ArxivFetchError):
            _ArxivSession().get('https://example.test')
        self.assertEqual(get.call_count, 2)
        self.assertEqual(self.waits, [200])

    @patch('requests.Session.get')
    def test_timeout_and_503_recover(self, get):
        get.side_effect = [requests.Timeout('timed out'), response(503), response(200)]
        self.assertEqual(_ArxivSession().get('https://example.test').status_code, 200)
        self.assertEqual(self.waits, [30, 60])

    @patch('requests.Session.get')
    def test_nonretryable_status_not_retried(self, get):
        get.return_value = response(400)
        self.assertEqual(_ArxivSession().get('https://example.test').status_code, 400)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(self.waits, [])

    @patch('requests.Session.get')
    def test_successive_requests_are_paced(self, get):
        get.return_value = response(200)
        session = _ArxivSession()
        session.get('https://example.test/1')
        session.get('https://example.test/2')
        self.assertEqual(self.waits, [3])

    def test_retry_after_http_date_and_invalid_values(self):
        future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=90))
        self.assertGreater(_ArxivSession._retry_after(future), 88)
        self.assertLessEqual(_ArxivSession._retry_after(future), 90)
        for value in (None, '', 'bad', '-5', 'NaN', 'Infinity'):
            self.assertEqual(_ArxivSession._retry_after(value), 0)
        self.assertEqual(_ArxivSession._retry_after('9' * 5000), float('inf'))
        self.assertEqual(_ArxivSession._retry_after('Wed, 01 Jan 2020 00:00:00 GMT'), 0)

    @patch('requests.Session.get')
    def test_real_client_429_recovery_and_query_filters(self, get):
        get.side_effect = [response(429), response(200, content=PAPER_FEED)]
        with patch('arxiv_fetcher.Config.SEARCH_KEYWORDS', ['tweezer array']), patch(
            'arxiv_fetcher.Config.SEARCH_CATEGORIES', ['quant-ph']
        ):
            papers = ArxivFetcher().fetch_recent_papers(days_back=2, max_results=20)
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]['matched_keywords'], ['tweezer array'])
        query = parse_qs(urlsplit(get.call_args.args[0]).query)['search_query'][0]
        self.assertIn('cat:quant-ph', query)
        self.assertIn('submittedDate:', query)
        self.assertIn('atom array', query)
        self.assertEqual(self.waits, [30])

    @patch('requests.Session.get')
    def test_real_client_empty_success(self, get):
        get.return_value = response(200)
        self.assertEqual(ArxivFetcher().fetch_recent_papers(), [])
        self.assertEqual(get.call_count, 1)

    @patch('requests.Session.get')
    def test_real_client_exhaustion_raises_instead_of_empty(self, get):
        get.side_effect = [response(429) for _ in range(4)]
        with self.assertRaises(ArxivFetchError):
            ArxivFetcher().fetch_recent_papers()
        self.assertEqual(get.call_count, 4)

    @patch('requests.Session.get')
    def test_later_page_failure_is_not_returned_as_complete(self, get):
        two_results = PAPER_FEED.replace(b'>1</opensearch:totalResults>', b'>2</opensearch:totalResults>')
        get.side_effect = [response(200, content=two_results)] + [response(429) for _ in range(4)]
        with self.assertRaises(ArxivFetchError):
            ArxivFetcher().fetch_recent_papers(max_results=2)
        self.assertEqual(get.call_count, 5)

    @patch('requests.Session.get')
    def test_real_client_strict_keyword_filter_preserved(self, get):
        get.return_value = response(200, content=PAPER_FEED)
        with patch('arxiv_fetcher.Config.SEARCH_KEYWORDS', ['microring']):
            self.assertEqual(ArxivFetcher().fetch_recent_papers(), [])


if __name__ == '__main__':
    unittest.main()

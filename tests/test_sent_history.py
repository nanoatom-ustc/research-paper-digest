import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from main import PaperDailyDigest
from sent_history import SentHistory, paper_keys


def paper(number, **extra):
    return dict({"id": "2610.%05dv1" % number, "title": "Paper %s" % number,
                 "published": "2026-10-%02d" % number}, **extra)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "sent.json"
        env = patch.dict(os.environ, {"SENT_HISTORY_PATH": str(self.path)})
        env.start()
        self.addCleanup(env.stop)

    def digest(self, papers, success=True, failed=False):
        with patch("main.Config.SEARCH_SOURCES", []):
            digest = PaperDailyDigest()
        fetcher = Mock(source_name="arXiv")
        fetcher.fetch_recent_papers.return_value = papers
        digest.fetchers = [fetcher]
        if failed:
            broken = Mock(source_name="APS")
            broken.fetch_recent_papers.side_effect = RuntimeError("offline")
            digest.fetchers.append(broken)
        digest.email_sender = Mock()
        digest.email_sender.send_digest.return_value = success
        return digest

    def test_second_run_does_not_resend_and_keeps_new_papers(self):
        first = self.digest([paper(1)])
        self.assertTrue(first.run())
        second = self.digest([paper(1), paper(2)])
        self.assertTrue(second.run())
        self.assertEqual(second.email_sender.send_digest.call_args.args[0], [paper(2)])

    def test_failed_mail_is_not_marked_and_can_be_retried(self):
        self.assertFalse(self.digest([paper(1)], success=False).run())
        self.assertFalse(self.path.exists())
        retry = self.digest([paper(1)])
        self.assertTrue(retry.run())
        self.assertEqual(retry.email_sender.send_digest.call_args.args[0], [paper(1)])

    def test_partial_source_mail_records_delivered_papers(self):
        self.assertFalse(self.digest([paper(1)], failed=True).run())
        recovered = self.digest([paper(1)])
        self.assertTrue(recovered.run())
        self.assertEqual(recovered.email_sender.send_digest.call_args.args[0], [])

    def test_filter_precedes_limit_and_unsent_overflow_is_not_recorded(self):
        with patch("main.Config.MAX_RESULTS", 1):
            self.assertTrue(self.digest([paper(3)]).run())
            second = self.digest([paper(3), paper(2), paper(1)])
            self.assertTrue(second.run())
            self.assertEqual(second.email_sender.send_digest.call_args.args[0], [paper(2)])
            third = self.digest([paper(3), paper(2), paper(1)])
            self.assertTrue(third.run())
            self.assertEqual(third.email_sender.send_digest.call_args.args[0], [paper(1)])

    def test_doi_and_arxiv_versions_normalized(self):
        first = paper(1, doi="HTTPS://DOI.ORG/10.1234/AbC ")
        history = SentHistory(self.path)
        self.assertEqual(history.select([first], 10), [first])
        history.record_sent()
        for duplicate in (paper(1, id="2610.00001v8"),
                          {"doi": "doi:10.1234/abc"},
                          {"article_url": "https://arxiv.org/abs/2610.00001v2"},
                          {"pdf_url": "http://arxiv.org/pdf/2610.00001v4.pdf"}):
            self.assertEqual(SentHistory(self.path).select([duplicate], 10), [])

    def test_cross_source_aliases_survive_reload(self):
        preprint = paper(1, doi="10.1234/test")
        journal = {"doi": "10.1234/TEST", "published": "2026-10-02"}
        history = SentHistory(self.path)
        self.assertEqual(len(history.select([journal, preprint], 10)), 1)
        history.record_sent()
        self.assertEqual(SentHistory(self.path).select([paper(1, id="2610.00001v2")], 10), [])

    def test_fallback_title_and_old_style_arxiv(self):
        self.assertEqual(paper_keys({"title": " Same  TITLE! "}), paper_keys({"title": "same title"}))
        self.assertEqual(paper_keys({"id": "quant-ph/0601001v1"}),
                         paper_keys({"arxiv_url": "https://arxiv.org/abs/quant-ph/0601001v3"}))

    def test_corrupt_history_fails_before_fetch_or_mail(self):
        for content in ('{', '{"version":2,"keys":[]}', '{"version":1,"keys":[4]}'):
            self.path.write_text(content)
            digest = self.digest([paper(1)])
            self.assertFalse(digest.run())
            digest.fetchers[0].fetch_recent_papers.assert_not_called()
            digest.email_sender.send_digest.assert_not_called()
            self.assertEqual(self.path.read_text(), content)

    def test_save_failure_is_visible_and_preserves_previous_history(self):
        history = SentHistory(self.path)
        history.select([paper(1)], 10)
        history.record_sent()
        before = self.path.read_bytes()
        with patch("sent_history.os.replace", side_effect=OSError("disk failed")):
            self.assertFalse(self.digest([paper(2)]).run())
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

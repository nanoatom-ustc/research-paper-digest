import unittest
from unittest.mock import Mock, patch

from email_sender import EmailSender
from main import PaperDailyDigest, main


PAPER = {"id": "paper-1", "title": "Quantum paper", "published": "2026-10-07", "source": "APS"}


def source(name, papers=None, error=None):
    fetcher = Mock(source_name=name)
    fetcher.fetch_recent_papers.return_value = papers or []
    fetcher.fetch_recent_papers.side_effect = error
    return fetcher


class DigestFailureTests(unittest.TestCase):
    def make_digest(self, fetchers):
        with patch("main.Config.SEARCH_SOURCES", []):
            digest = PaperDailyDigest()
        digest.fetchers = fetchers
        digest.email_sender = Mock()
        digest.email_sender.send_digest.return_value = True
        return digest

    def test_success_retains_original_call(self):
        digest = self.make_digest([source("arXiv", [PAPER])])
        self.assertTrue(digest.run())
        args, kwargs = digest.email_sender.send_digest.call_args
        self.assertEqual(args[0], [PAPER])
        self.assertEqual(len(args[1]), 1)
        self.assertEqual(kwargs, {})
        self.assertEqual(digest.failed_sources, [])

    def test_empty_success_is_successful(self):
        digest = self.make_digest([source("arXiv")])
        self.assertTrue(digest.run())
        digest.email_sender.send_digest.assert_called_once_with([], [])

    def test_failed_only_sends_warning_and_returns_failure(self):
        digest = self.make_digest([source("arXiv", error=RuntimeError("429"))])
        self.assertFalse(digest.run())
        digest.email_sender.send_digest.assert_called_once_with([], [], failed_sources=["arXiv"])

    def test_mixed_sources_continue_after_failure(self):
        healthy = source("APS", [PAPER])
        digest = self.make_digest([source("arXiv", error=RuntimeError("429")), healthy])
        self.assertFalse(digest.run())
        healthy.fetch_recent_papers.assert_called_once()
        args, kwargs = digest.email_sender.send_digest.call_args
        self.assertEqual(args[0], [PAPER])
        self.assertEqual(kwargs, {"failed_sources": ["arXiv"]})

    def test_failed_sources_reset_after_recovery(self):
        fetcher = source("arXiv", error=RuntimeError("429"))
        digest = self.make_digest([fetcher])
        self.assertFalse(digest.run())
        fetcher.fetch_recent_papers.side_effect = None
        self.assertTrue(digest.run())
        self.assertEqual(digest.failed_sources, [])
        digest.email_sender.send_digest.assert_called_with([], [])

    def test_multiple_failed_sources_are_reported(self):
        digest = self.make_digest([source(name, error=RuntimeError("offline")) for name in ("arXiv", "APS")])
        self.assertFalse(digest.run())
        self.assertEqual(digest.failed_sources, ["arXiv", "APS"])

    def test_mail_failure_returns_failure(self):
        digest = self.make_digest([source("arXiv", [PAPER])])
        digest.email_sender.send_digest.return_value = False
        self.assertFalse(digest.run())

    @patch("main.Config.validate")
    @patch.dict("os.environ", {"RUN_MODE": "ci"})
    def test_cli_failure_exit_status(self, validate):
        digest = self.make_digest([source("arXiv", error=RuntimeError("429"))])
        with patch("main.PaperDailyDigest", return_value=digest):
            self.assertEqual(main(), 1)


class EmailFailureRenderingTests(unittest.TestCase):
    def render(self, papers, failed_sources=None):
        sender = EmailSender()
        sender.sender = "sender@example.test"
        sender.recipient = "recipient@example.test"
        with patch.object(sender, "_send_email") as send:
            self.assertTrue(sender.send_digest(papers, ["Summary"] * len(papers), failed_sources))
        msg = send.call_args.args[0]
        text, html = [part.get_payload(decode=True).decode("utf-8") for part in msg.get_payload()]
        return str(msg["Subject"]), text, html

    def test_empty_success_keeps_normal_notice(self):
        subject, text, html = self.render([])
        self.assertNotIn("数据不完整", subject)
        self.assertIn("今日无新论文", text)
        self.assertIn("系统运行正常", html)

    def test_failed_empty_never_claims_no_papers_or_normal_operation(self):
        subject, text, html = self.render([], ["arXiv"])
        self.assertIn("数据不完整", subject)
        for body in (text, html):
            self.assertIn("数据源查询失败：arXiv", body)
            self.assertIn("无法确认", body)
            self.assertNotIn("今日无新论文", body)
            self.assertNotIn("系统运行正常", body)

    def test_mixed_failure_keeps_papers_and_warning_in_both_formats(self):
        subject, text, html = self.render([PAPER], ["arXiv"])
        self.assertIn("数据不完整", subject)
        for body in (text, html):
            self.assertIn(PAPER["title"], body)
            self.assertIn("本次摘要不完整", body)
            self.assertIn("arXiv", body)

    def test_failure_labels_are_html_escaped(self):
        _, text, html = self.render([], ["<failed&source>"])
        self.assertIn("<failed&source>", text)
        self.assertIn("&lt;failed&amp;source&gt;", html)
        self.assertNotIn("<failed&source>", html)

    def test_successful_paper_render_has_no_warning(self):
        subject, text, html = self.render([PAPER])
        self.assertNotIn("数据不完整", subject)
        for body in (text, html):
            self.assertIn(PAPER["title"], body)
            self.assertNotIn("数据源查询失败", body)


if __name__ == "__main__":
    unittest.main()

# main.py - GitHub Actions entry point
import logging
import os
import sys
from datetime import datetime

from aps_fetcher import APSFetcher
from arxiv_fetcher import ArxivFetcher
from config import Config
from email_sender import EmailSender
from nature_fetcher import NatureFetcher
from optica_fetcher import OpticaFetcher
from paper_utils import generate_summary
from science_fetcher import ScienceFetcher


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class PaperDailyDigest:
    def __init__(self):
        factories = {
            "arxiv": ArxivFetcher,
            "aps": APSFetcher,
            "nature": NatureFetcher,
            "science": ScienceFetcher,
            "optica": OpticaFetcher,
        }
        self.fetchers = [factories[source]() for source in Config.SEARCH_SOURCES]
        self.email_sender = EmailSender()
        self.failed_sources = []

    def fetch_papers(self, days_back):
        papers = []
        self.failed_sources = []
        for fetcher in self.fetchers:
            logger.info("正在查询数据源: %s", fetcher.source_name)
            try:
                source_papers = fetcher.fetch_recent_papers(
                    days_back=days_back, max_results=Config.MAX_RESULTS
                )
                papers.extend(source_papers)
            except Exception:
                self.failed_sources.append(fetcher.source_name)
                logger.exception("Data source failed: %s", fetcher.source_name)

        # A DOI may appear in more than one source. Preserve the first result and
        # apply MAX_RESULTS to the combined digest, matching the old global limit.
        unique_papers = {}
        for paper in papers:
            key = (paper.get("doi") or paper.get("id") or paper.get("article_url", "")).lower()
            if key and key not in unique_papers:
                unique_papers[key] = paper

        return sorted(
            unique_papers.values(), key=lambda paper: paper.get("published", ""), reverse=True
        )[: Config.MAX_RESULTS]

    def run(self, test_mode=False):
        logger.info("=" * 60)
        logger.info("Starting paper digest task - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        try:
            days_back = 0 if test_mode else Config.FETCH_DAYS
            papers = self.fetch_papers(days_back)
            summaries = [generate_summary(paper) for paper in papers]

            if self.failed_sources:
                logger.error("Digest is incomplete; failed sources: %s", ", ".join(self.failed_sources))
            if papers:
                logger.info("Found %s matching papers", len(papers))
            elif not self.failed_sources:
                logger.info("No matching papers found; sending an empty digest notice")

            # Keep the original two-argument call for successful fetches.
            options = {"failed_sources": self.failed_sources} if self.failed_sources else {}
            if not self.email_sender.send_digest(papers, summaries, **options):
                logger.error("Email sending failed")
                return False
            if self.failed_sources:
                logger.error("Warning digest sent, but task failed because source data is incomplete")
                return False
            logger.info("Task completed; sent digest for %s papers", len(papers))
            return True
        except Exception as exc:
            logger.exception("Task failed: %s", exc)
            return False
        finally:
            logger.info("=" * 60)

    def run_once(self, test_mode=False):
        return self.run(test_mode=test_mode)


# Backward-compatible class name for code importing the original entry point.
ArxivDailyDigest = PaperDailyDigest


def main():
    try:
        Config.validate()
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        return 1

    digest = PaperDailyDigest()
    if os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("RUN_MODE") == "ci":
        return 0 if digest.run_once(test_mode=False) else 1
    if Config.TEST_MODE:
        return 0 if digest.run(test_mode=True) else 1
    return 0 if digest.run_once(test_mode=False) else 1


if __name__ == "__main__":
    sys.exit(main())

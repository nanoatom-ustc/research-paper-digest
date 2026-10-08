import logging
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import arxiv
import requests

from config import Config
from paper_utils import (
    find_matching_keywords,
    generate_summary,
    keyword_aliases,
    truncate_text,
)

logger = logging.getLogger(__name__)


class ArxivFetchError(RuntimeError):
    """The arXiv query failed; this is not an empty successful result."""


class _ArxivSession(requests.Session):
    """Bounded retries at the HTTP layer, where Retry-After is still available.

    arxiv.py 2.1.1 discards response headers in its HTTPError. Its own retries
    are disabled to avoid multiplying attempts. Pace every request, including
    retries and pagination, and never shorten a server-requested wait.
    """

    MAX_ATTEMPTS = 4
    MAX_RETRY_WAIT = 300.0
    REQUEST_INTERVAL = 3.0
    RETRY_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self):
        super().__init__()
        self._last_request = None

    @staticmethod
    def _retry_after(value):
        if not value:
            return 0.0
        value = value.strip()
        if value.isdigit():
            try:
                return float(value)
            except OverflowError:
                return float("inf")
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0.0

    def get(self, url, **kwargs):
        kwargs.setdefault("timeout", (10, 30))
        waited = 0.0
        for attempt in range(self.MAX_ATTEMPTS):
            if self._last_request is not None:
                pause = self.REQUEST_INTERVAL - (time.monotonic() - self._last_request)
                if pause > 0:
                    time.sleep(pause)
            self._last_request = time.monotonic()
            retry_after = 0.0
            try:
                response = super().get(url, **kwargs)
            except (requests.Timeout, requests.ConnectionError) as exc:
                error = exc
            else:
                if response.status_code not in self.RETRY_STATUSES:
                    return response
                retry_after = self._retry_after(response.headers.get("Retry-After"))
                error = requests.HTTPError(
                    f"arXiv HTTP {response.status_code}", response=response
                )
                response.close()

            if attempt == self.MAX_ATTEMPTS - 1:
                raise error
            delay = max(30.0 * (2 ** attempt), retry_after)
            if delay > self.MAX_RETRY_WAIT - waited:
                # Fail rather than retry before a long Retry-After expires.
                raise ArxivFetchError(
                    "arXiv Retry-After exceeds the remaining retry wait budget"
                ) from error
            logger.warning(
                "arXiv request failed (%s); retry %s/%s in %.1fs",
                error, attempt + 1, self.MAX_ATTEMPTS - 1, delay,
            )
            time.sleep(delay)
            waited += delay


class ArxivFetcher:
    source_name = "arXiv"

    def __init__(self):
        self.client = arxiv.Client(delay_seconds=3.0, num_retries=0)
        # Pinned arxiv==2.1.1 has no public session injection API. Keep its
        # parser/query/pagination unchanged and replace only the HTTP session.
        self.client._session.close()
        self.client._session = _ArxivSession()
        self.keywords = Config.SEARCH_KEYWORDS

    def fetch_recent_papers(self, days_back: int = 1, max_results: int = 50) -> List[Dict]:
        """Fetch recent arXiv papers matching the configured terms and categories."""
        try:
            query_terms = []
            for keyword in self.keywords:
                query_terms.extend(keyword_aliases(keyword))
            keyword_query = " OR ".join([f'all:"{term}"' for term in query_terms])
            query = f"({keyword_query})"

            if Config.SEARCH_CATEGORIES:
                cat_query = " OR ".join([f"cat:{cat}" for cat in Config.SEARCH_CATEGORIES])
                query += f" AND ({cat_query})"

            if days_back > 0:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days_back)
                date_range = f"[{start_date.strftime('%Y%m%d')} TO {end_date.strftime('%Y%m%d')}]"
                query += f" AND submittedDate:{date_range}"

            logger.info("arXiv 搜索查询: %s", query)
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )

            papers = []
            for result in self.client.results(search):
                matched_kws = find_matching_keywords(
                    result.title, result.summary, self.keywords
                )
                if not matched_kws:
                    logger.info("跳过未在标题或摘要中严格命中主题的 arXiv 论文: %s", result.title[:60])
                    continue

                paper = {
                    "id": result.get_short_id(),
                    "title": result.title,
                    "authors": [author.name for author in result.authors],
                    "abstract": result.summary,
                    "pdf_url": result.pdf_url,
                    "published": result.published.strftime("%Y-%m-%d %H:%M"),
                    "primary_category": result.primary_category,
                    "categories": result.categories,
                    "arxiv_url": result.entry_id,
                    "article_url": result.entry_id,
                    "source": self.source_name,
                    "journal": "",
                    "doi": result.doi or "",
                    "matched_keywords": matched_kws,
                }
                papers.append(paper)
                logger.info("找到 arXiv 论文: %s", paper["title"][:60])

            logger.info("arXiv 共找到 %s 篇相关论文", len(papers))
            return papers
        except Exception as exc:
            logger.error("获取 arXiv 论文失败: %s", exc, exc_info=True)
            raise ArxivFetchError("arXiv query did not complete") from exc

    def generate_summary(self, paper: Dict) -> str:
        """Backward-compatible summary API."""
        return generate_summary(paper)

    def _truncate_text(self, text: str, max_length: int) -> str:
        """Backward-compatible text truncation API."""
        return truncate_text(text, max_length)

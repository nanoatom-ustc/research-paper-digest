from __future__ import annotations

import html
import logging
import re
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests

from config import Config
from paper_utils import find_matching_keywords, generate_summary, keyword_query_terms

logger = logging.getLogger(__name__)


class CrossrefFetchError(RuntimeError):
    """A publisher query is incomplete; retain its successful partial results."""

    def __init__(self, message, papers):
        super().__init__(message)
        self.papers = papers


class CrossrefFetcher:
    """Shared Crossref implementation for publisher DOI-prefix sources."""

    source_name = "Crossref"
    doi_prefix = ""
    venue_fallback = "Journal"
    REQUEST_INTERVAL = 1.0
    MAX_ATTEMPTS = 4
    MAX_RETRY_WAIT = 300.0
    RETRY_STATUSES = {429, 500, 502, 503, 504}
    _last_request = None  # Shared across publishers using the same API.
    _cooldown_until = 0.0

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        journals: Optional[List[str]] = None,
        excluded_journals: Optional[List[str]] = None,
    ):
        self.session = session or requests.Session()
        self.keywords = Config.SEARCH_KEYWORDS
        self.journals = journals or []
        self.excluded_journals = excluded_journals or []
        self._retry_wait = 0.0

    @property
    def api_url(self):
        return f"https://api.crossref.org/prefixes/{self.doi_prefix}/works"

    def fetch_recent_papers(self, days_back: int = 1, max_results: int = 50) -> List[Dict]:
        if max_results <= 0:
            return []

        self._retry_wait = 0.0
        failures = []
        papers_by_doi = {}
        rows = min(max(max_results, 20), 100)
        for keyword in self.keywords:
            for query_term in keyword_query_terms(keyword):
                try:
                    for item in self._fetch_keyword(query_term, days_back, rows):
                        paper = self._normalise_item(item)
                        if paper and self._journal_allowed(paper["journal"]):
                            existing = papers_by_doi.get(paper["doi"])
                            if existing:
                                existing["matched_keywords"] = sorted(
                                    set(existing["matched_keywords"] + paper["matched_keywords"])
                                )
                            else:
                                papers_by_doi[paper["doi"]] = paper
                except requests.RequestException as exc:
                    failures.append(query_term)
                    logger.warning(
                        "%s/Crossref 查询失败（检索词 %s）: %s",
                        self.source_name,
                        query_term,
                        exc,
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    failures.append(query_term)
                    logger.warning(
                        "%s/Crossref 响应解析失败（检索词 %s）: %s",
                        self.source_name,
                        query_term,
                        exc,
                    )

        papers = sorted(papers_by_doi.values(), key=lambda paper: paper["published"], reverse=True)
        result = papers[:max_results]
        logger.info("%s 共找到 %s 篇相关论文", self.source_name, len(result))
        if failures:
            raise CrossrefFetchError(
                f"{self.source_name} queries failed: {', '.join(failures)}", result
            )
        return result

    def _fetch_keyword(self, keyword: str, days_back: int, rows: int) -> List[dict]:
        filters = ["type:journal-article"]
        if days_back > 0:
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=days_back)
            filters.extend([
                f"from-pub-date:{start_date.isoformat()}",
                f"until-pub-date:{end_date.isoformat()}",
            ])

        response = self._get_with_retry(
            self.api_url,
            params={
                "query.bibliographic": keyword,
                "filter": ",".join(filters),
                "rows": rows,
                "sort": "published",
                "order": "desc",
            },
            headers={"User-Agent": self._user_agent()},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["message"]["items"]

    def _get_with_retry(self, url, **kwargs):
        for attempt in range(self.MAX_ATTEMPTS):
            cooldown = CrossrefFetcher._cooldown_until - time.monotonic()
            if cooldown > 0:
                if cooldown > self.MAX_RETRY_WAIT - self._retry_wait:
                    raise requests.RequestException("Crossref Retry-After exceeds remaining wait budget")
                time.sleep(cooldown)
                self._retry_wait += cooldown
            if CrossrefFetcher._last_request is not None:
                pause = self.REQUEST_INTERVAL - (time.monotonic() - CrossrefFetcher._last_request)
                if pause > 0:
                    time.sleep(pause)
            CrossrefFetcher._last_request = time.monotonic()
            retry_after = 0.0
            try:
                response = self.session.get(url, **kwargs)
            except (requests.Timeout, requests.ConnectionError) as exc:
                error = exc
            else:
                if response.status_code not in self.RETRY_STATUSES:
                    return response
                retry_after = self._retry_after(response.headers.get("Retry-After"))
                CrossrefFetcher._cooldown_until = max(
                    CrossrefFetcher._cooldown_until, time.monotonic() + retry_after
                )
                error = requests.HTTPError(f"Crossref HTTP {response.status_code}", response=response)
                response.close()
            if attempt == self.MAX_ATTEMPTS - 1:
                raise error
            delay = max(30.0 * 2 ** attempt, retry_after)
            if delay > self.MAX_RETRY_WAIT - self._retry_wait:
                raise requests.RequestException("Crossref retry wait budget exhausted") from error
            logger.warning("%s request failed (%s); retry %s/%s in %.1fs",
                           self.source_name, error, attempt + 1, self.MAX_ATTEMPTS - 1, delay)
            time.sleep(delay)
            self._retry_wait += delay

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

    def _normalise_item(self, item: dict) -> Optional[Dict]:
        doi = (item.get("DOI") or "").strip()
        title = " ".join(item.get("title") or []).strip()
        if not doi or not title:
            return None

        journal = " ".join(item.get("container-title") or []).strip()
        abstract = self._clean_abstract(item.get("abstract", ""))
        matched = find_matching_keywords(title, abstract, self.keywords)
        if not matched:
            logger.info(
                "跳过未在标题或摘要中严格命中主题的 %s 论文: %s",
                self.source_name,
                title[:60],
            )
            return None

        authors = [self._author_name(author) for author in item.get("author", [])]
        authors = [author for author in authors if author]
        article_url = item.get("URL") or f"https://doi.org/{doi}"

        return {
            "id": doi,
            "doi": doi,
            "title": title,
            "authors": authors,
            "abstract": abstract or "Crossref 未提供摘要，请通过文章链接查看。",
            "pdf_url": self._pdf_url(item),
            "published": self._published_date(item),
            "primary_category": journal or self.venue_fallback,
            "categories": item.get("subject") or [],
            "arxiv_url": article_url,
            "article_url": article_url,
            "source": self.source_name,
            "journal": journal or self.venue_fallback,
            "matched_keywords": matched,
        }

    def _journal_allowed(self, journal: str) -> bool:
        if any(self._journal_matches(journal, excluded) for excluded in self.excluded_journals):
            return False
        return not self.journals or any(
            self._journal_matches(journal, configured) for configured in self.journals
        )

    @staticmethod
    def _journal_matches(journal: str, configured: str) -> bool:
        normalised = re.sub(r"[^a-z0-9]", "", journal.lower())
        configured_normalised = re.sub(r"[^a-z0-9]", "", configured.lower())
        acronym = "".join(word[0] for word in re.findall(r"[a-z0-9]+", journal.lower()))
        return configured_normalised == normalised or configured_normalised == acronym

    @staticmethod
    def _clean_abstract(value: str) -> str:
        if not value:
            return ""
        without_tags = re.sub(r"<[^>]+>", " ", value)
        return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()

    @staticmethod
    def _author_name(author: dict) -> str:
        if author.get("name"):
            return author["name"].strip()
        return " ".join(
            part for part in [author.get("given", ""), author.get("family", "")] if part
        ).strip()

    @staticmethod
    def _published_date(item: dict) -> str:
        for key in ("published-online", "published-print", "published", "created"):
            date_parts = item.get(key, {}).get("date-parts", [])
            if date_parts and date_parts[0]:
                parts = list(date_parts[0]) + [1, 1]
                return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d} 00:00"
        return ""

    @staticmethod
    def _pdf_url(item: dict) -> str:
        for link in item.get("link", []):
            if link.get("content-type") == "application/pdf":
                return link.get("URL", "")
        return ""

    @staticmethod
    def generate_summary(paper: Dict) -> str:
        return generate_summary(paper)

    @staticmethod
    def _user_agent() -> str:
        if Config.CROSSREF_MAILTO:
            return f"research-paper-digest/2.2 (mailto:{Config.CROSSREF_MAILTO})"
        return "research-paper-digest/2.2"

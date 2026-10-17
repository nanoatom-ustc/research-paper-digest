import unittest
from unittest.mock import patch

from aps_fetcher import APSFetcher
from nature_fetcher import NatureFetcher
from optica_fetcher import OpticaFetcher
from science_fetcher import ScienceFetcher


class FakeResponse:
    status_code = 200

    def __init__(self, items):
        self.items = items

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"items": self.items}}


class FakeSession:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.items)


APS_ITEM = {
    "DOI": "10.1103/PhysRevLett.123.456",
    "title": ["Integrated photonics with trapped atoms"],
    "container-title": ["Physical Review Letters"],
    "abstract": "<jats:p>An <b>integrated photonics</b> result.</jats:p>",
    "author": [{"given": "Ada", "family": "Lovelace"}],
    "published-online": {"date-parts": [[2026, 8, 25]]},
    "URL": "https://doi.org/10.1103/PhysRevLett.123.456",
    "link": [{"content-type": "application/pdf", "URL": "https://example.test/paper.pdf"}],
    "subject": ["Physics"],
}


class APSFetcherTests(unittest.TestCase):
    @patch("aps_fetcher.Config.SEARCH_KEYWORDS", ["integrated photonics", "trapped atoms"])
    @patch("aps_fetcher.Config.APS_JOURNALS", [])
    @patch("aps_fetcher.Config.APS_EXCLUDE_JOURNALS", [])
    def test_fetch_normalises_and_deduplicates_crossref_results(self):
        session = FakeSession([APS_ITEM])
        fetcher = APSFetcher(session=session)

        papers = fetcher.fetch_recent_papers(days_back=2, max_results=10)

        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source"], "APS")
        self.assertEqual(paper["journal"], "Physical Review Letters")
        self.assertEqual(paper["authors"], ["Ada Lovelace"])
        self.assertEqual(paper["pdf_url"], "https://example.test/paper.pdf")
        self.assertNotIn("<jats:p>", paper["abstract"])
        self.assertEqual(
            set(paper["matched_keywords"]), {"integrated photonics", "trapped atoms"}
        )
        self.assertEqual(len(session.calls), 2)
        self.assertIn("type:journal-article", session.calls[0][1]["params"]["filter"])
        self.assertIn("from-pub-date:", session.calls[0][1]["params"]["filter"])

    @patch("aps_fetcher.Config.SEARCH_KEYWORDS", ["integrated photonics"])
    @patch("aps_fetcher.Config.APS_JOURNALS", ["PRA"])
    @patch("aps_fetcher.Config.APS_EXCLUDE_JOURNALS", [])
    def test_journal_filter_excludes_nonmatching_journal(self):
        fetcher = APSFetcher(session=FakeSession([APS_ITEM]))
        self.assertEqual(fetcher.fetch_recent_papers(days_back=1, max_results=10), [])

    @patch("aps_fetcher.Config.SEARCH_KEYWORDS", ["integrated photonics"])
    @patch("aps_fetcher.Config.APS_JOURNALS", ["PRL"])
    @patch("aps_fetcher.Config.APS_EXCLUDE_JOURNALS", [])
    def test_journal_filter_accepts_common_acronym(self):
        fetcher = APSFetcher(session=FakeSession([APS_ITEM]))
        self.assertEqual(len(fetcher.fetch_recent_papers(days_back=1, max_results=10)), 1)

    @patch("aps_fetcher.Config.SEARCH_KEYWORDS", ["quantum"])
    @patch("aps_fetcher.Config.APS_JOURNALS", [])
    @patch(
        "aps_fetcher.Config.APS_EXCLUDE_JOURNALS",
        ["Physical Review B", "Physical Review D", "PRB", "PRD"],
    )
    def test_prb_and_prd_are_excluded(self):
        items = []
        for suffix, journal in (("PhysRevB.1", "Physical Review B"), ("PhysRevD.2", "Physical Review D")):
            item = dict(APS_ITEM)
            item.update({
                "DOI": f"10.1103/{suffix}",
                "title": [f"A quantum result in {journal}"],
                "container-title": [journal],
            })
            items.append(item)
        fetcher = APSFetcher(session=FakeSession(items))
        self.assertEqual(fetcher.fetch_recent_papers(days_back=1, max_results=10), [])


class PublisherFetcherTests(unittest.TestCase):
    @patch("nature_fetcher.Config.SEARCH_KEYWORDS", ["quantum"])
    @patch("nature_fetcher.Config.NATURE_JOURNALS", [])
    def test_nature_uses_1038_prefix_and_normalises_source(self):
        item = dict(APS_ITEM)
        item.update({
            "DOI": "10.1038/s41567-026-00001",
            "title": ["A quantum result"],
            "container-title": ["Nature Physics"],
        })
        session = FakeSession([item])
        papers = NatureFetcher(session=session).fetch_recent_papers(days_back=1, max_results=10)
        self.assertEqual(papers[0]["source"], "Nature")
        self.assertEqual(papers[0]["journal"], "Nature Physics")
        self.assertIn("/prefixes/10.1038/works", session.calls[0][0])

    @patch("science_fetcher.Config.SEARCH_KEYWORDS", ["quantum"])
    @patch("science_fetcher.Config.SCIENCE_JOURNALS", [])
    def test_science_uses_1126_prefix_and_includes_subjournals(self):
        item = dict(APS_ITEM)
        item.update({
            "DOI": "10.1126/sciadv.example",
            "title": ["A quantum result"],
            "container-title": ["Science Advances"],
        })
        session = FakeSession([item])
        papers = ScienceFetcher(session=session).fetch_recent_papers(days_back=1, max_results=10)
        self.assertEqual(papers[0]["source"], "Science")
        self.assertEqual(papers[0]["journal"], "Science Advances")
        self.assertIn("/prefixes/10.1126/works", session.calls[0][0])

    @patch("optica_fetcher.Config.SEARCH_KEYWORDS", ["quantum"])
    @patch("optica_fetcher.Config.OPTICA_JOURNALS", ["Optica", "Optics Express"])
    def test_optica_uses_1364_prefix_and_includes_configured_journals(self):
        items = []
        for suffix, journal in (("optica.example", "Optica"), ("oe.example", "Optics Express")):
            item = dict(APS_ITEM)
            item.update({
                "DOI": f"10.1364/{suffix}",
                "title": [f"A quantum result in {journal}"],
                "container-title": [journal],
            })
            items.append(item)
        session = FakeSession(items)
        papers = OpticaFetcher(session=session).fetch_recent_papers(days_back=1, max_results=10)
        self.assertEqual({paper["journal"] for paper in papers}, {"Optica", "Optics Express"})
        self.assertTrue(all(paper["source"] == "Optica" for paper in papers))
        self.assertIn("/prefixes/10.1364/works", session.calls[0][0])

    @patch("optica_fetcher.Config.SEARCH_KEYWORDS", ["quantum"])
    @patch("optica_fetcher.Config.OPTICA_JOURNALS", ["Optica", "Optics Express"])
    def test_optica_allowlist_excludes_other_optica_journals(self):
        item = dict(APS_ITEM)
        item.update({
            "DOI": "10.1364/ao.example",
            "title": ["A quantum result"],
            "container-title": ["Applied Optics"],
        })
        papers = OpticaFetcher(session=FakeSession([item])).fetch_recent_papers(
            days_back=1, max_results=10
        )
        self.assertEqual(papers, [])

    @patch("nature_fetcher.Config.SEARCH_KEYWORDS", ["quantum"])
    @patch("nature_fetcher.Config.NATURE_JOURNALS", ["Nature"])
    def test_nature_allowlist_uses_exact_title_not_prefix(self):
        item = dict(APS_ITEM)
        item.update({
            "DOI": "10.1038/nmat.example",
            "title": ["A quantum result"],
            "container-title": ["Nature Materials"],
        })
        papers = NatureFetcher(session=FakeSession([item])).fetch_recent_papers(
            days_back=1, max_results=10
        )
        self.assertEqual(papers, [])

    @patch("science_fetcher.Config.SEARCH_KEYWORDS", ["quantum"])
    @patch("science_fetcher.Config.SCIENCE_JOURNALS", ["Science"])
    def test_science_allowlist_uses_exact_title_not_prefix(self):
        item = dict(APS_ITEM)
        item.update({
            "DOI": "10.1126/scirobotics.example",
            "title": ["A quantum result"],
            "container-title": ["Science Robotics"],
        })
        papers = ScienceFetcher(session=FakeSession([item])).fetch_recent_papers(
            days_back=1, max_results=10
        )
        self.assertEqual(papers, [])


if __name__ == "__main__":
    unittest.main()

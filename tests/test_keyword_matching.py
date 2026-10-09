import unittest
from unittest.mock import patch

from optica_fetcher import OpticaFetcher
from paper_utils import (
    find_matching_keywords,
    keyword_matches,
    keyword_query_terms,
)


class FakeResponse:
    def __init__(self, items):
        self.items = items

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"items": self.items}}


class FakeSession:
    def __init__(self, items):
        self.items = items

    def get(self, url, **kwargs):
        return FakeResponse(self.items)


class KeywordMatchingTests(unittest.TestCase):
    def test_rejects_partial_crossref_match(self):
        title = "High-bandwidth coherence cloning using optical-phase-locking feedforward"
        abstract = "A coherent optical communication technique."
        self.assertEqual(
            find_matching_keywords(title, abstract, ["optical tweezers"]),
            [],
        )

    @patch("optica_fetcher.Config.SEARCH_KEYWORDS", ["optical tweezers"])
    @patch("optica_fetcher.Config.OPTICA_JOURNALS", ["Optica"])
    def test_optica_fetcher_drops_crossref_false_positive(self):
        item = {
            "DOI": "10.1364/optica.example",
            "title": [
                "High-bandwidth coherence cloning using optical-phase-locking feedforward"
            ],
            "container-title": ["Optica"],
            "abstract": "<jats:p>A coherent optical communication technique.</jats:p>",
            "published-online": {"date-parts": [[2026, 9, 1]]},
        }
        papers = OpticaFetcher(session=FakeSession([item])).fetch_recent_papers(
            days_back=3, max_results=30
        )
        self.assertEqual(papers, [])

    def test_matches_configured_topic_variants(self):
        cases = [
            ("Scalable tweezer arrays for neutral atoms", "tweezer array"),
            ("High-fidelity entangling gates and nonlocal circuits with neutral atoms", "neutral atom"),
            ("A neutral-atom quantum processor", "neutral atoms"),
            ("A micro-ring resonator platform", "microring"),
            ("Atoms trapped near a nano-fiber", "nanofiber"),
            ("Measurements of surface forces near a dielectric", "surface force"),
            ("A photonic integrated circuit for quantum networking", "PIC"),
            ("Low-loss PIC for atomic interfaces", "PIC"),
        ]
        for text, keyword in cases:
            with self.subTest(text=text, keyword=keyword):
                self.assertTrue(keyword_matches(text, keyword))

    def test_matches_tweezer_array_synonyms(self):
        variants = [
            "A programmable atom array for quantum simulation",
            "Multiplexed photonic links for neutral-atom arrays",
            "An atomic array coupled to a nanophotonic cavity",
            "Coherent control of an array of optical tweezers",
            "Reconfigurable arrays of tweezers",
            "Scalable atom-tweezer arrays",
            "Realization of a cavity-coupled Rydberg array",
            "Quantum simulation with Rydberg arrays",
        ]
        for text in variants:
            with self.subTest(text=text):
                self.assertTrue(keyword_matches(text, "tweezer array"))

    def test_tweezer_array_query_terms_include_broader_phrases(self):
        self.assertEqual(
            keyword_query_terms("tweezer array"),
            [
                "tweezer array",
                "atom array",
                "neutral atom array",
                "rydberg array",
                "array of optical tweezers",
            ],
        )

    def test_pic_requires_a_complete_term_or_expansion(self):
        self.assertFalse(keyword_matches("Topic modeling for optical data", "PIC"))
        self.assertEqual(
            keyword_query_terms("PIC"),
            ["PIC", "photonic integrated circuit", "integrated photonic circuit"],
        )


if __name__ == "__main__":
    unittest.main()

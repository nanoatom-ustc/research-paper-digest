import re
from typing import Dict, Iterable, List


_KEYWORD_ALIASES = {
    "tweezer array": (
        "tweezer array",
        "tweezer arrays",
        "optical tweezer array",
        "optical tweezer arrays",
        "atom tweezer array",
        "atom tweezer arrays",
        "atom array",
        "atom arrays",
        "atomic array",
        "atomic arrays",
        "neutral atom array",
        "neutral atom arrays",
        "rydberg array",
        "rydberg arrays",
        "array of tweezers",
        "arrays of tweezers",
        "array of optical tweezers",
        "arrays of optical tweezers",
    ),
    "pic": (
        "pic",
        "pics",
        "photonic integrated circuit",
        "photonic integrated circuits",
        "integrated photonic circuit",
        "integrated photonic circuits",
    ),
    "microring": ("microring", "microrings", "micro ring", "micro rings"),
    "nanofiber": ("nanofiber", "nanofibers", "nano fiber", "nano fibers"),
    "surface force": ("surface force", "surface forces"),
}


def _normalise_match_text(value: str) -> str:
    words_only = re.sub(r"[^a-z0-9]+", " ", (value or "").lower())
    return re.sub(r"\s+", " ", words_only).strip()


def keyword_aliases(keyword: str) -> List[str]:
    cleaned = keyword.strip()
    normalised = _normalise_match_text(cleaned)
    return list(_KEYWORD_ALIASES.get(normalised, (cleaned,)))


def keyword_query_terms(keyword: str) -> List[str]:
    """Return a compact set of API query terms for semantic aliases."""
    normalised = _normalise_match_text(keyword)
    if normalised == "tweezer array":
        return [
            "tweezer array",
            "atom array",
            "neutral atom array",
            "rydberg array",
            "array of optical tweezers",
        ]
    if normalised == "pic":
        return ["PIC", "photonic integrated circuit", "integrated photonic circuit"]
    return [keyword.strip()]


def keyword_matches(text: str, keyword: str) -> bool:
    normalised_text = f" {_normalise_match_text(text)} "
    return any(
        f" {_normalise_match_text(alias)} " in normalised_text
        for alias in keyword_aliases(keyword)
        if _normalise_match_text(alias)
    )


def find_matching_keywords(title: str, abstract: str, keywords: Iterable[str]) -> List[str]:
    """Require a configured topic to occur in the paper title or abstract."""
    searchable = f"{title or ''} {abstract or ''}"
    return [
        keyword.strip()
        for keyword in keywords
        if keyword.strip() and keyword_matches(searchable, keyword)
    ]


def truncate_text(text: str, max_length: int) -> str:
    text = (text or "").replace("\n", " ")
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated


def generate_summary(paper: Dict) -> str:
    abstract = paper.get("abstract", "")
    authors = paper.get("authors", [])
    source = paper.get("source", "arXiv")
    venue = paper.get("journal") or paper.get("primary_category") or "未知"
    article_url = paper.get("article_url") or paper.get("arxiv_url") or paper.get("pdf_url", "")

    summary_lines = [
        "=" * 60,
        f"📄 标题: {paper.get('title', '')}",
        "",
        f"👥 作者: {', '.join(authors[:3])}{' 等' if len(authors) > 3 else ''}",
        f"📅 发布时间: {paper.get('published', '')}",
        f"🗂️ 来源: {source} | 期刊/分类: {venue}",
        f"🏷️ 命中关键词: {', '.join(paper.get('matched_keywords', ['未知']))}",
        "",
        "📝 摘要:",
        truncate_text(abstract, 800) + ("..." if len(abstract) > 800 else ""),
        "",
        "🔗 链接:",
        f"文章: {article_url}",
    ]
    if paper.get("pdf_url"):
        summary_lines.append(f"PDF: {paper['pdf_url']}")
    summary_lines.extend(["=" * 60, ""])
    return "\n".join(summary_lines)

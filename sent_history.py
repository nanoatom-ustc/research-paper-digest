"""Durable identities of papers accepted by SMTP; no email addresses or abstracts."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from urllib.parse import unquote, urlsplit, urlunsplit


def paper_keys(paper):
    keys = set()
    doi = unquote(str(paper.get("doi") or "")).strip().lower()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi)
    if doi:
        keys.add("doi:" + doi)
    for field in ("id", "arxiv_url", "article_url", "pdf_url"):
        value = unquote(str(paper.get(field) or "")).strip()
        if not value:
            continue
        arxiv = re.fullmatch(
            r"(?:(?:https?://)?(?:export\.)?arxiv\.org/(?:abs|pdf)/|arxiv:)?"
            r"((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}))(?:v\d+)?(?:\.pdf)?/?",
            value, re.IGNORECASE,
        )
        if arxiv:
            keys.add("arxiv:" + arxiv.group(1).lower())
        elif re.match(r"https?://(?:dx\.)?doi\.org/", value, re.IGNORECASE):
            keys.add("doi:" + re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.IGNORECASE).lower())
        elif field == "id":
            keys.add("id:" + value.lower())
        elif field != "pdf_url":
            parts = urlsplit(value)
            if parts.scheme and parts.netloc:
                keys.add("url:" + urlunsplit(("https", parts.netloc.lower(), parts.path.rstrip("/"), "", "")))
    # Use title only when there is no stable identifier; avoid conflating
    # unrelated papers that happen to share a title.
    if not keys:
        title = " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", paper.get("title") or "").casefold()))
        if title:
            keys.add("title:" + hashlib.sha256(title.encode("utf-8")).hexdigest())
    if not keys:
        raise ValueError("Paper has no usable identity")
    return keys


class SentHistory:
    def __init__(self, path):
        self.path = Path(path)
        self.keys = set()
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("version") != 1
                    or not isinstance(data.get("keys"), list)
                    or any(not isinstance(key, str) or not key for key in data["keys"])):
                raise ValueError("Invalid sent-paper history; refusing to resend")
            self.keys = set(data["keys"])

    def select(self, papers, limit):
        # Merge all aliases before filtering/capping, so a DOI learned later
        # still resolves to the earlier arXiv record.
        groups = []
        for paper in papers:
            keys = paper_keys(paper)
            matches = [group for group in groups if group[1] & keys]
            if matches:
                for group in matches:
                    keys.update(group[1])
                first = matches[0][0]
                groups = [group for group in groups if group not in matches]
                groups.append((first, keys))
            else:
                groups.append((paper, keys))
        selected = []
        self.selected_keys = set()
        for paper, keys in sorted(groups, key=lambda group: group[0].get("published", ""), reverse=True):
            if keys & self.keys:
                self.keys.update(keys)
            elif len(selected) < limit:
                selected.append(paper)
                self.selected_keys.update(keys)
        return selected

    def record_sent(self):
        self.keys.update(self.selected_keys)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".sent-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "keys": sorted(self.keys)}, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

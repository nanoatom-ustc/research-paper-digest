import os

try:
    from dotenv import load_dotenv
except ImportError:  # Environment variables still work when python-dotenv is unavailable.
    def load_dotenv():
        return False

load_dotenv()


def _csv_env(name, default=""):
    value = os.getenv(name, default)
    return [item.strip().strip('"').strip("'") for item in value.split(",") if item.strip()]


class Config:
    EMAIL_SENDER = os.getenv("EMAIL_SENDER")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
    RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

    FETCH_DAYS = int(os.getenv("FETCH_DAYS", 1))
    MAX_RESULTS = int(os.getenv("MAX_RESULTS", 50))

    SEARCH_KEYWORDS = _csv_env(
        "SEARCH_KEYWORDS",
        "tweezer array,neutral atom,neutral atoms,PIC,microring,nanofiber,surface force",
    )

    SEARCH_SOURCES = [
        source.lower()
        for source in _csv_env("SEARCH_SOURCES", "arxiv,aps,nature,science,optica")
    ]
    SEARCH_CATEGORIES = _csv_env("SEARCH_CATEGORIES")

    # Publisher-specific allowlists. Defaults intentionally keep the digest focused.
    APS_JOURNALS = _csv_env("APS_JOURNALS")
    NATURE_JOURNALS = _csv_env(
        "NATURE_JOURNALS",
        "Nature,Nature Physics,Nature Photonics,Nature Communications,"
        "npj Quantum Information,Nature Reviews Physics",
    )
    SCIENCE_JOURNALS = _csv_env("SCIENCE_JOURNALS", "Science,Science Advances")
    OPTICA_JOURNALS = _csv_env("OPTICA_JOURNALS", "Optica,Optics Express")

    APS_EXCLUDE_JOURNALS = _csv_env(
        "APS_EXCLUDE_JOURNALS", "Physical Review B,Physical Review D,PRB,PRD"
    )
    CROSSREF_MAILTO = os.getenv("CROSSREF_MAILTO", "").strip()

    SCHEDULE_TIME = "09:00"
    TEST_MODE = False
    LOG_FILE = "logs/paper_digest.log"

    @classmethod
    def validate(cls):
        if not cls.EMAIL_SENDER or not cls.EMAIL_PASSWORD or not cls.RECIPIENT_EMAIL:
            raise ValueError("邮箱配置不完整，请检查 .env 文件或 GitHub Secrets")

        supported_sources = {"arxiv", "aps", "nature", "science", "optica"}
        unknown_sources = set(cls.SEARCH_SOURCES) - supported_sources
        if unknown_sources:
            raise ValueError(f"不支持的数据源: {', '.join(sorted(unknown_sources))}")
        if not cls.SEARCH_SOURCES:
            raise ValueError("SEARCH_SOURCES 至少需要包含一个支持的数据源")
        return True

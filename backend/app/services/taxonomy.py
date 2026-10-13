"""Deterministic topic and category classification.

Keyword based on purpose: it is transparent, testable and works with no external
model. Topics are used for search, interest matching and the fit score.
"""

from __future__ import annotations

import re

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ai": ("ai", "artificial intelligence", "llm", "llms", "genai", "generative", "gpt", "agents", "agentic", "copilot"),
    "ml": ("machine learning", "ml", "deep learning", "neural", "mlops", "computer vision", "nlp", "data science", "pytorch", "tensorflow"),
    "data": ("data", "analytics", "big data", "databricks", "spark", "sql", "etl", "warehouse", "lakehouse", "kafka", "data engineering", "postgres"),
    "web": ("javascript", "typescript", "react", "vue", "angular", "node", "nodejs", "frontend", "front-end", "css", "html", "web", "svelte", "nextjs", "jsconf", "jsnation"),
    "mobile": ("android", "ios", "flutter", "swift", "kotlin", "react native", "mobile", "droidcon", "fluttercon", "swiftui"),
    "cloud_devops": ("devops", "kubernetes", "k8s", "cloud", "aws", "gcp", "azure", "cncf", "sre", "docker", "terraform", "platform engineering", "observability", "grpc", "kubecon"),
    "security": ("security", "cybersecurity", "infosec", "hacking", "ctf", "appsec", "blackhat", "black hat", "defcon", "owasp", "pentest"),
    "opensource": ("open source", "open-source", "oss", "linux", "apache", "foss", "ubuntu", "ubucon", "gnome", "kde"),
    "languages": ("python", "java", "rust", "golang", "php", "ruby", "scala", "kotlin", "c++", "cpp", "elixir", "haskell", "clojure", ".net", "dotnet", "pycon", "rubyconf"),
    "design_ux": ("ux", "design", "accessibility", "a11y", "ui"),
    "blockchain": ("blockchain", "web3", "ethereum", "crypto", "solidity", "defi"),
    "iot_embedded": ("iot", "embedded", "robotics", "hardware", "arduino", "raspberry"),
    "quantum": ("quantum",),
    "product_leadership": ("product", "leadership", "management", "agile", "engineering manager"),
    "testing": ("testing", "qa", "quality assurance", "test automation"),
    "career": ("internship", "career", "placement", "job", "hiring", "fellowship"),
}

TOPIC_LABELS = {
    "ai": "AI",
    "ml": "Machine learning",
    "data": "Data & analytics",
    "web": "Web development",
    "mobile": "Mobile",
    "cloud_devops": "Cloud & DevOps",
    "security": "Security",
    "opensource": "Open source",
    "languages": "Programming languages",
    "design_ux": "Design & UX",
    "blockchain": "Blockchain",
    "iot_embedded": "IoT & embedded",
    "quantum": "Quantum",
    "product_leadership": "Product & leadership",
    "testing": "Testing & QA",
    "career": "Careers",
}

# Query/profile words -> topic keys (superset of the keyword table for natural queries)
QUERY_TOPIC_HINTS: dict[str, tuple[str, ...]] = {
    "ai": ("ai", "artificial intelligence", "genai", "llm", "generative ai"),
    "ml": ("machine learning", "ml", "deep learning", "data science"),
    "data": ("data", "data engineering", "analytics", "big data", "sql"),
    "web": ("web", "frontend", "javascript", "react", "css"),
    "mobile": ("mobile", "android", "ios", "flutter"),
    "cloud_devops": ("devops", "cloud", "kubernetes", "aws"),
    "security": ("security", "cybersecurity", "ctf", "hacking"),
    "opensource": ("open source", "oss", "linux"),
    "languages": ("python", "java", "rust", "golang"),
    "design_ux": ("ux", "design"),
    "blockchain": ("blockchain", "web3"),
    "iot_embedded": ("iot", "embedded", "robotics"),
}

CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("hackathon", ("hackathon", "hack day", "hackday", "hack week", "hackfest", "code sprint", "buildathon", "ideathon", "datathon")),
    ("internship", ("internship", "intern ", "fellowship", "apprenticeship")),
    ("competition", ("competition", "contest", "challenge", "olympiad", "ctf", "cup", "championship")),
    ("workshop", ("workshop", "bootcamp", "boot camp", "training", "masterclass", "tutorial", "hands-on", "hands on")),
    ("meetup", ("meetup", "meet-up", "user group", "community day", "chapter")),
    ("conference", ("conference", "summit", "conf", "con ", "symposium", "devfest", "droidcon", "pycon", "jsconf", "kubecon", "expo", "forum")),
]

_WORD = re.compile(r"[a-z0-9+.#]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def topics_from_text(text: str) -> list[str]:
    """Return topic keys whose keywords appear as whole words/phrases in text."""
    if not text:
        return []
    low = " " + re.sub(r"[^a-z0-9+.# ]+", " ", text.lower()) + " "
    found: list[str] = []
    for topic, words in TOPIC_KEYWORDS.items():
        for w in words:
            if f" {w} " in low:
                found.append(topic)
                break
    return found


def classify_category(title: str, extra_text: str = "", default: str = "other") -> str:
    blob = f" {title.lower()} {extra_text.lower()} "
    for category, words in CATEGORY_KEYWORDS:
        for w in words:
            if w in blob:
                return category
    return default


def topics_from_interests(interests: list[str]) -> set[str]:
    out: set[str] = set()
    for item in interests:
        out.update(topics_from_text(item))
        low = item.strip().lower()
        for topic, hints in QUERY_TOPIC_HINTS.items():
            if low in hints:
                out.add(topic)
    return out

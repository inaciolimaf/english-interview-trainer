"""Session plan (saved in interview_sessions.plan): what this interview will cover.

Chosen deterministically from the job posting and the resume — no LLM call, so creating
a session is instant and free. The interviewer prompt then follows the plan.
"""

import random
import re
from dataclasses import dataclass

TECHNICAL_AREAS: dict[str, tuple[str, ...]] = {
    "language and runtime": ("node", "typescript", "javascript", "python", "go", "java", "kotlin", "runtime", "event loop"),
    "databases and data modeling": ("postgres", "mysql", "sql", "mongo", "dynamo", "database", "data model", "orm"),
    "caching": ("redis", "memcached", "cache", "cdn"),
    "messaging and queues": ("kafka", "rabbit", "sqs", "queue", "pub/sub", "event", "stream"),
    "concurrency and async processing": ("concurren", "async", "worker", "thread", "parallel", "celery"),
    "API design": ("api", "rest", "graphql", "grpc", "endpoint", "integration"),
    "testing and quality": ("test", "tdd", "quality", "ci"),
    "observability and production": ("observability", "monitoring", "logging", "metrics", "on-call", "incident", "sre"),
    "cloud and infrastructure": ("aws", "gcp", "azure", "docker", "kubernetes", "terraform", "serverless", "lambda"),
    "security": ("security", "auth", "oauth", "encryption", "compliance", "pci", "gdpr"),
}

BEHAVIORAL_THEMES = (
    "a production incident you handled",
    "a conflict or strong disagreement with a teammate",
    "a time you led or influenced without authority",
    "a failure or mistake and what you learned",
    "a difficult delivery under pressure or changing requirements",
)


@dataclass(frozen=True)
class DesignProblem:
    id: str
    title: str
    statement: str  # what the interviewer says when presenting the problem
    domains: tuple[str, ...]
    deep_dives: tuple[str, ...]


SYSTEM_DESIGN_PROBLEMS: tuple[DesignProblem, ...] = (
    DesignProblem("url_shortener", "URL shortener",
        "Design a URL shortening service like Bitly: users submit a long URL and get a short link that redirects.",
        ("general", "saas", "marketing"),
        ("short code generation and collisions", "read-heavy caching", "analytics on clicks", "custom aliases and expiry")),
    DesignProblem("rate_limiter", "Distributed rate limiter",
        "Design a rate limiter used by a public API gateway, limiting requests per API key across many servers.",
        ("api", "platform", "infrastructure", "saas", "devtools"),
        ("token bucket vs sliding window", "shared state in Redis", "race conditions", "behavior when the limiter store is down")),
    DesignProblem("notifications", "Notification system",
        "Design a system that sends email, SMS and push notifications triggered by events from other services.",
        ("general", "saas", "e-commerce", "marketplace"),
        ("fan-out and queues", "retries and idempotency", "user preferences and rate limits", "provider failover")),
    DesignProblem("payments", "Payment processing",
        "Design the payment flow of an online store: charging a card through an external provider and recording the result.",
        ("fintech", "payments", "e-commerce", "banking"),
        ("idempotency keys", "exactly-once effects with an external provider", "double-entry ledger", "reconciliation")),
    DesignProblem("wallet_ledger", "Digital wallet",
        "Design a digital wallet where users hold a balance, receive money and transfer it to other users.",
        ("fintech", "banking", "payments", "crypto"),
        ("ledger consistency", "concurrent transfers", "auditability", "fraud checks latency")),
    DesignProblem("chat", "Chat service",
        "Design a one-to-one and group chat service with online presence and message history.",
        ("social", "communication", "collaboration", "gaming"),
        ("websocket connection management", "message ordering", "offline delivery", "group fan-out")),
    DesignProblem("news_feed", "News feed",
        "Design the home feed of a social network that shows recent posts from people a user follows.",
        ("social", "media", "content", "community"),
        ("fan-out on write vs read", "celebrity accounts", "ranking", "cache invalidation")),
    DesignProblem("ride_sharing", "Ride matching",
        "Design the backend that matches riders with nearby drivers for a ride-hailing app.",
        ("mobility", "logistics", "transportation", "delivery"),
        ("geospatial indexing", "location update throughput", "matching consistency", "surge pricing")),
    DesignProblem("shipment_tracking", "Real-time shipment tracking",
        "Design a service that ingests tracking events from many carriers and shows customers the live status "
        "and history of their shipments.",
        ("logistics", "shipping", "delivery", "e-commerce", "supply chain", "tracking"),
        ("event ingestion and carrier integrations", "out-of-order and duplicate events",
         "read-heavy status queries and caching", "pushing updates to customers")),
    DesignProblem("food_delivery", "Food delivery orders",
        "Design the order system of a food delivery app, from checkout to the courier picking up the order.",
        ("delivery", "marketplace", "logistics", "food", "e-commerce"),
        ("order state machine", "restaurant and courier notifications", "peak load at lunch", "consistency between services")),
    DesignProblem("inventory_checkout", "E-commerce checkout and inventory",
        "Design checkout for an online store with limited stock, including flash sales.",
        ("e-commerce", "retail", "marketplace"),
        ("reserving stock and overselling", "hot items under flash sales", "cart vs order", "payment failures")),
    DesignProblem("video_streaming", "Video streaming",
        "Design a video platform where creators upload videos and viewers stream them on any device.",
        ("media", "streaming", "entertainment", "content", "education"),
        ("upload and transcoding pipeline", "CDN and adaptive bitrate", "metadata storage", "view counting")),
    DesignProblem("file_storage", "File storage and sync",
        "Design a file storage service like Dropbox that syncs files across a user's devices.",
        ("cloud", "storage", "collaboration", "saas"),
        ("chunking and deduplication", "sync conflicts", "metadata database", "large file uploads")),
    DesignProblem("autocomplete", "Search autocomplete",
        "Design the autocomplete suggestions for a search box, returning results as the user types.",
        ("search", "e-commerce", "content", "travel"),
        ("trie vs search index", "latency budget", "ranking and freshness", "personalization")),
    DesignProblem("metrics", "Metrics and monitoring",
        "Design a system that collects metrics from thousands of servers and lets engineers query dashboards and alerts.",
        ("devtools", "observability", "infrastructure", "platform", "saas"),
        ("write throughput and time-series storage", "downsampling", "alert evaluation", "high cardinality")),
    DesignProblem("booking", "Booking and reservations",
        "Design a hotel or appointment booking system that prevents double bookings.",
        ("travel", "hospitality", "healthcare", "booking"),
        ("double-booking prevention", "holds that expire", "search vs booking consistency", "partner integrations")),
    DesignProblem("job_scheduler", "Distributed job scheduler",
        "Design a service that runs scheduled and delayed background jobs for many internal teams.",
        ("infrastructure", "platform", "devtools", "general"),
        ("exactly-once vs at-least-once execution", "leader election", "retries and dead letters", "multi-tenant fairness")),
    DesignProblem("web_crawler", "Web crawler",
        "Design a web crawler that downloads and indexes billions of pages.",
        ("search", "data", "ai", "analytics"),
        ("URL frontier and politeness", "deduplication", "distributed coordination", "storage of raw pages")),
)

SENIORITY_BAR = {
    "mid": "Expect solid fundamentals and practical experience; probe depth in one or two areas.",
    "senior": "Expect ownership, trade-off reasoning, production experience and clear communication; "
              "push on scale, failure modes and alternatives.",
}


def _text(*parts: object) -> str:
    return " ".join(str(p) for p in parts if p).lower()


def _mentions(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def choose_design_problem(job: dict | None, recent_ids: set[str], rng: random.Random) -> DesignProblem:
    domain = _text(job.get("domain")) if job else ""
    context = _text(job.get("summary"), *job.get("responsibilities", [])) if job else ""

    def score(p: DesignProblem) -> int:
        # the extracted business domain weighs more than words in the description
        return sum(3 * _mentions(domain, d) + _mentions(context, d) for d in p.domains)

    candidates = [p for p in SYSTEM_DESIGN_PROBLEMS if p.id not in recent_ids] or list(SYSTEM_DESIGN_PROBLEMS)
    best = max(score(p) for p in candidates)
    if best == 0:
        pool = [p for p in candidates if "general" in p.domains] or candidates
    else:
        pool = [p for p in candidates if score(p) == best]
    return rng.choice(pool)


def choose_technical_areas(stack: list[str], job: dict | None, rng: random.Random, n: int = 5) -> list[str]:
    text = _text(*stack, *(job or {}).get("responsibilities", []), *(job or {}).get("nice_to_have", []))
    scored = [(sum(1 for kw in kws if kw in text), area) for area, kws in TECHNICAL_AREAS.items()]
    rng.shuffle(scored)
    scored.sort(key=lambda x: x[0], reverse=True)
    return [area for _, area in scored[:n]]


def build_plan(
    session_type: str, job: dict | None, profile: dict | None, recent_problem_ids: set[str],
    rng: random.Random | None = None,
) -> dict:
    rng = rng or random.Random()
    stack = (job or {}).get("required_stack") or (profile or {}).get("stack") or []
    stack_source = "job" if (job or {}).get("required_stack") else ("resume" if stack else "none")

    if session_type == "system_design":
        p = choose_design_problem(job, recent_problem_ids, rng)
        return {
            "problem_id": p.id, "problem_title": p.title, "problem_statement": p.statement,
            "deep_dives": list(p.deep_dives), "stack": stack, "stack_source": stack_source,
        }
    if session_type == "technical":
        return {
            "stack": stack, "stack_source": stack_source,
            "areas": choose_technical_areas(stack, job, rng),
        }
    projects = [
        {"name": pr.get("name"), "description": pr.get("description"), "impact": pr.get("impact")}
        for pr in (profile or {}).get("projects", [])[:4]
    ]
    themes = list(BEHAVIORAL_THEMES)
    rng.shuffle(themes)
    return {"themes": themes, "anchor_projects": projects}

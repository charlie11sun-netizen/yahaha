"""Source-code security policy shared by validators and project services."""

FORBIDDEN_PATTERNS = (
    (r"eval\s*\(", "eval()"),
    (r"new\s+Function", "new Function"),
    (r"document\.cookie", "document.cookie"),
    (r"window\.(parent|top)(?!\s*\.\s*postMessage)", "parent/top access"),
    (r"\blocalStorage\b", "localStorage"),
    (r"\bsessionStorage\b", "sessionStorage"),
    (r"fetch\s*\(", "fetch()"),
    (r"XMLHttpRequest", "XMLHttpRequest"),
    (r"\bWebSocket\b", "WebSocket"),
    (r"\bimport\s*\(", "dynamic import()"),
    (r"\bnavigator\.sendBeacon\b", "sendBeacon"),
    (r"\bEventSource\b", "EventSource"),
    (r"<script[^>]+src=[\"']https?://", "external script"),
    (r"https?://(?!www\.w3\.org)", "external URL"),
)

__all__ = ["FORBIDDEN_PATTERNS"]

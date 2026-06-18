"""生成产物校验 —— Sandbox QA 的确定性部分。

拦截外联 / 远程执行类 API（Prompt Injection、数据外泄、远程代码执行的防线），
并做基本结构与体积检查。QA 不过则由 graph 回到 Coder 重试。
"""
import re

# (正则, 展示名)。沙箱 iframe 无 allow-same-origin，这些 API 要么危险要么直接报错。
_FORBIDDEN = [
    (r"\bfetch\s*\(", "fetch()"),
    (r"\bXMLHttpRequest\b", "XMLHttpRequest"),
    (r"\bWebSocket\b", "WebSocket"),
    (r"\beval\s*\(", "eval()"),
    (r"\bnew\s+Function\s*\(", "new Function()"),
    (r"https?://(?!www\.w3\.org)", "external URL"),
    (r"\bdocument\.cookie\b", "document.cookie"),
    (r"window\.(parent|top)\b", "parent/top access"),
]

MAX_BYTES = 400_000


def extract_html(raw: str) -> str:
    """从模型输出取出 HTML（容忍 ```html``` 代码块包裹与前后多余文本）。"""
    if not raw:
        return ""
    m = re.search(r"```(?:html)?\s*(.*?)```", raw, re.S | re.I)
    s = (m.group(1) if m else raw).strip()
    low = s.lower()
    i = low.find("<!doctype")
    if i < 0:
        i = low.find("<html")
    return s[i:].strip() if i >= 0 else s


def validate_html(html: str) -> list[str]:
    issues: list[str] = []
    if not html or len(html) < 200:
        return ["output too short / not an HTML document"]
    low = html.lower()
    if "<html" not in low and "<!doctype" not in low:
        issues.append("missing <html> document")
    if "<script" not in low:
        issues.append("no <script> — game is not runnable")
    if len(html.encode("utf-8")) > MAX_BYTES:
        issues.append(f"bundle too large (> {MAX_BYTES // 1000}KB)")
    for pattern, label in _FORBIDDEN:
        if re.search(pattern, html, re.I):
            issues.append(f"forbidden API: {label}")
    return issues

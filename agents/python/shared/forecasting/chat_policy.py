"""Use MAF's native first-tool requirement for explicit saved-report reads.

Conversation text can identify a report, but is not evidence of a fresh database
read. This deliberately narrow policy does not route ordinary product questions,
greetings, or requests to create a new forecast.
"""

import re

_READ_REPORT = re.compile(
    r"\b(?:read|retrieve|load|open|list|fetch|review|show)\b.{0,120}"
    r"\b(?:reports?|saved\s+(?:forecasts?|analys[ie]s))\b"
    r"|(?:读取|查看|调出|打开|列出|查询|重读).{0,30}(?:报告|已保存.{0,8}(?:预测|分析))",
    re.IGNORECASE,
)
_UUID = re.compile(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", re.IGNORECASE)


def required_report_tool(message: str, agent_name: str, role: str) -> str | None:
    if role != "store_manager" or agent_name not in {"orchestrator", "inventory-fulfillment"}:
        return None
    normalised = " ".join(message.split())
    normalised = re.sub(
        r"\b(?:do not|don't|never)\s+(?:read|retrieve|load|open|list|fetch|review|show)\b"
        r"|(?:不要|无需|不必)(?:读取|查看|调出|打开|列出|查询|重读)",
        "",
        normalised,
        flags=re.IGNORECASE,
    )
    if not _READ_REPORT.search(normalised):
        return None
    if agent_name == "orchestrator":
        return "call_specialist_agent"
    if not _UUID.search(normalised) and re.search(
        r"\b(?:list|latest|newest|recent)\b|列出|最新|最近", normalised, re.I
    ):
        return "list_saved_sales_analyses"
    return "get_saved_sales_analysis"

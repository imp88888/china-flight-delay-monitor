from bs4 import BeautifulSoup
from .base import BaseAdapter
from utils.http import request_with_retry
import re

class VariflightAdapter(BaseAdapter):
    source = "variflight"

    def _build_url(self, flight_no, date):
        # 注意：真实的页面 URL 可能不同。此处为示例模板，必要时根据实际页面调整。
        return f"https://www.variflight.com/flight/{flight_no}.html?date={date}"

    def parse(self, html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        # 尝试常见选择器，页面结构有变时需调节
        def text_or_none(sel):
            el = soup.select_one(sel)
            return el.get_text(strip=True) if el else None

        status = text_or_none(".flight-status") or text_or_none(".status")
        scheduled_dep = text_or_none(".plan-dep") or text_or_none(".scheduled-dep")
        scheduled_arr = text_or_none(".plan-arr") or text_or_none(".scheduled-arr")
        actual_dep = text_or_none(".actual-dep")
        actual_arr = text_or_none(".actual-arr")

        # 尝试从状态字段或页面中解析延误分钟（示例性的正则）
        delay_min = None
        if status:
            m = re.search(r"延误(\d+)分钟", status)
            if m:
                delay_min = int(m.group(1))

        # 兜底：如果有实际/计划时间，尝试计算 delay（简化）
        # 注意：实际项目中应解析时间并计算分钟差

        return {
            "status": status,
            "scheduled_dep": scheduled_dep,
            "scheduled_arr": scheduled_arr,
            "actual_dep": actual_dep,
            "actual_arr": actual_arr,
            "delay_min": delay_min,
            "source": self.source,
            "raw": (html[:2000] if html else None),
        }

    def fetch(self, flight_no: str, date: str) -> dict:
        url = self._build_url(flight_no, date)
        html = request_with_retry(url)
        return self.parse(html)

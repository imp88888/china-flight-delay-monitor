from bs4 import BeautifulSoup
from .base import BaseAdapter
from utils.http import request_with_retry
import re

class FliggyAdapter(BaseAdapter):
    source = "fliggy"

    def _build_url(self, flight_no, date):
        # 飞猪旅行示例页面 URL（可能需要根据实际页面调整）
        return f"https://flights.alitrip.com/flight/{flight_no}.html?date={date}"

    def parse(self, html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        def text_or_none(sel):
            el = soup.select_one(sel)
            return el.get_text(strip=True) if el else None

        status = text_or_none(".flight-status") or text_or_none(".status")
        scheduled_dep = text_or_none(".plan-dep")
        scheduled_arr = text_or_none(".plan-arr")
        actual_dep = text_or_none(".actual-dep")
        actual_arr = text_or_none(".actual-arr")

        delay_min = None
        if status:
            m = re.search(r"延误(\d+)分钟", status)
            if m:
                delay_min = int(m.group(1))

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

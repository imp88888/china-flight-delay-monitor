# adapters package
from .base import BaseAdapter
from .scrape_variflight import VariflightAdapter
from .scrape_ctrip import CtripAdapter
from .scrape_fliggy import FliggyAdapter

__all__ = ["BaseAdapter", "VariflightAdapter", "CtripAdapter", "FliggyAdapter"]

from abc import ABC, abstractmethod

class BaseAdapter(ABC):
    source: str

    @abstractmethod
    def fetch(self, flight_no: str, date: str) -> dict:
        """Return standardized dict:
           {status, scheduled_dep, scheduled_arr, actual_dep, actual_arr, delay_min, source, raw}
        """
        raise NotImplementedError

from typing import Optional

class ExchangeAPIError(Exception):
    """Exception raised when exchange API call fails"""
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)
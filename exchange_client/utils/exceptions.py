from typing import Optional

class ExchangeAPIError(Exception):
    """Exception raised when exchange API call fails"""
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


"""Custom exceptions for trading operations"""
class TradingException(Exception):
    """Base exception for trading errors"""
    def __init__(self, message: str, error_type: str = None, details: dict = None):
        self.message = message
        self.error_type = error_type
        self.details = details or {}
        super().__init__(self.message)
    
    def __str__(self):
        return self.message


class InvalidQuantityError(TradingException):
    """Raised when order quantity is invalid"""
    def __init__(self, message: str, quantity=None, **kwargs):
        super().__init__(message, error_type="invalid_quantity", details={"quantity": quantity, **kwargs})


class InvalidPriceError(TradingException):
    """Raised when order price is invalid"""
    def __init__(self, message: str, price=None, **kwargs):
        super().__init__(message, error_type="invalid_price", details={"price": price, **kwargs})


class InsufficientBalanceError(TradingException):
    """Raised when account has insufficient balance"""
    def __init__(self, message: str, required=None, available=None, **kwargs):
        super().__init__(
            message, 
            error_type="insufficient_balance",
            details={"required": required, "available": available, **kwargs}
        )
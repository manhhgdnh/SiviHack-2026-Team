class ReviewError(Exception):
    """Safe public errors: never return raw provider payloads, prompts or credentials."""

    def __init__(self, code: str, message: str, status: int = 422, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable

    def payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "retryable": self.retryable}}

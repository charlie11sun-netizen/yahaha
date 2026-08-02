class ServiceError(Exception):
    """Business-layer error that routers translate into HTTP responses."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail

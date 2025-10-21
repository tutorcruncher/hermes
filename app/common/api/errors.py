from fastapi import HTTPException


class HTTP403(HTTPException):
    """403 Forbidden"""

    def __init__(self, detail: str = 'Forbidden'):
        super().__init__(status_code=403, detail=detail)


class HTTP404(HTTPException):
    """404 Not Found"""

    def __init__(self, detail: str = 'Not found'):
        super().__init__(status_code=404, detail=detail)


class HTTP400(HTTPException):
    """400 Bad Request"""

    def __init__(self, detail: str = 'Bad request'):
        super().__init__(status_code=400, detail=detail)

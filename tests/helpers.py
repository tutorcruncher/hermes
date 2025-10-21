"""
Test helpers and utilities for Hermes v4 tests.
"""

from typing import Any, Dict, Optional


class MockResponse:
    """Mock HTTP response object for testing"""

    def __init__(
        self,
        json_data: Optional[Dict[str, Any]] = None,
        status_code: int = 200,
        text: str = '',
        headers: Optional[Dict[str, str]] = None,
        raise_for_status_error: bool = False,
    ):
        self._json_data = json_data or {}
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._raise_for_status_error = raise_for_status_error

    def json(self) -> Dict[str, Any]:
        """Return JSON data"""
        if self._json_data is None:
            raise ValueError('No JSON data')
        return self._json_data

    def raise_for_status(self):
        """Simulate raise_for_status behavior"""
        if self._raise_for_status_error or self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                message=f'Error {self.status_code}',
                request=httpx.Request('GET', 'http://example.com'),
                response=self,
            )

    # Make the object compatible with AsyncMock expectations
    async def aclose(self):
        """Mock aclose method for httpx compatibility"""
        pass


def create_mock_response(data: Dict[str, Any], status_code: int = 200) -> MockResponse:
    """Helper to create a mock response with data"""
    return MockResponse(json_data=data, status_code=status_code)


def create_error_response(status_code: int = 500, text: str = 'Internal Server Error') -> MockResponse:
    """Helper to create an error response"""
    return MockResponse(status_code=status_code, text=text, raise_for_status_error=True)

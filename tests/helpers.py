"""
Test helpers and utilities for Hermes v4 tests.
"""

from datetime import datetime, timedelta
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


def fake_gcal_builder(
    admin_email: str = 'climan@example.com',
    error: bool = False,
    start_dt: datetime | None = None,
    meeting_dur_mins: int = 90,
):
    """
    Mock Google Calendar resource builder for testing.

    Args:
        admin_email: Email address to use in calendar response
        error: If True, raises an error (for testing error handling)
        start_dt: Start datetime for busy period (defaults to 2026-07-08 11:00 UTC)
        meeting_dur_mins: Duration of busy period in minutes

    Returns:
        MockGCalResource class (not instance) that can be used with mock.side_effect
    """

    def as_iso_8601(dt: datetime):
        return dt.isoformat().replace('+00:00', 'Z')

    class MockGCalResource:
        def execute(self):
            from datetime import timezone

            utc = timezone.utc
            start = start_dt or datetime(2026, 7, 8, 11, tzinfo=utc)
            end = start + timedelta(minutes=meeting_dur_mins)
            return {'calendars': {admin_email: {'busy': [{'start': as_iso_8601(start), 'end': as_iso_8601(end)}]}}}

        def query(self, body: dict):
            self.body = body
            return self

        def freebusy(self, *args, **kwargs):
            return self

        def events(self):
            return self

        def insert(self, *args, **kwargs):
            return self

    return MockGCalResource


def create_mock_gcal_resource(admin_email: str):
    """
    Create a mock Google Calendar resource with empty calendar.

    Args:
        admin_email: Email address to use in calendar response

    Returns:
        MockGCalResource instance with no busy periods
    """

    class MockGCalResource:
        def execute(self):
            return {'calendars': {admin_email: {'busy': []}}}

        def query(self, body: dict):
            return self

        def freebusy(self, *args, **kwargs):
            return self

        def events(self):
            return self

        def insert(self, *args, **kwargs):
            return self

    return MockGCalResource()

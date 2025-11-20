"""
Custom exceptions for Hermes application.
"""


class MeetingBookingError(Exception):
    """Raised when a meeting cannot be booked"""

    pass


class DealCreationError(Exception):
    """Raised when deal cannot be created due to configuration errors"""

    pass

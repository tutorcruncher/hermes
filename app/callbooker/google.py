import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from app.core.config import settings

logger = logging.getLogger('hermes.google')


@dataclass
class AdminGoogleCalendar:
    """Google Calendar interface for admin users"""

    admin_email: str

    def __post_init__(self):
        self.resource = self._create_resource()

    def _create_resource(self) -> Resource:
        """Create Google Calendar API resource with service account credentials"""
        creds = service_account.Credentials.from_service_account_info(
            settings.google_credentials, scopes=['https://www.googleapis.com/auth/calendar']
        ).with_subject(self.admin_email)
        return build('calendar', 'v3', credentials=creds)

    def get_free_busy_slots(self, start: datetime, end: datetime) -> dict:
        """Query Google Calendar for busy slots in the given time range"""
        q_data = {
            'timeMin': start.isoformat(),
            'timeMax': end.isoformat(),
            'timeZone': 'utc',
            'groupExpansionMax': 100,
            'items': [{'id': self.admin_email}],
        }
        return self.resource.freebusy().query(body=q_data).execute()

    def create_cal_event(self, *, summary: str, description: str, start: datetime, end: datetime, contact_email: str):
        """Create a calendar event with Google Meet"""
        event = {
            'summary': summary,
            'description': description,
            'start': {'dateTime': start.isoformat()},
            'end': {'dateTime': end.isoformat()},
            'attendees': [{'email': self.admin_email}, {'email': contact_email}],
            'reminders': {'useDefault': True},
            'conferenceData': {
                'createRequest': {'requestId': f'{uuid4().hex}', 'conferenceSolutionKey': {'type': 'hangoutsMeet'}}
            },
        }

        try:
            (
                self.resource.events()
                .insert(calendarId=self.admin_email, sendNotifications=True, body=event, conferenceDataVersion=1)
                .execute()
            )
            logger.info(f'Created Google Calendar event: {summary} for {contact_email}')
        except HttpError as e:
            logger.error(f'Error creating Google Calendar event: {e}', exc_info=True)
            raise

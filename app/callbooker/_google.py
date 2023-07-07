import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from ..settings import Settings

settings = Settings()

logger = logging.getLogger('google')


@dataclass
class AdminGoogleCalendar:
    admin_email: str

    def __post_init__(self):
        self.resource = self._create_resource()

    def _create_resource(self) -> Resource:
        creds = service_account.Credentials.from_service_account_info(
            settings.google_credentials, scopes=['https://www.googleapis.com/auth/calendar']
        ).with_subject(self.admin_email)
        return build('calendar', 'v3', credentials=creds)

    def get_free_busy_slots(self, start: datetime, end: datetime) -> dict:
        q_data = {
            'timeMin': start.isoformat(),
            'timeMax': (start + timedelta(days=1)).isoformat(),
            'timeZone': 'utc',
            'groupExpansionMax': 100,
            'items': [{'id': self.admin_email}],
        }
        return self.resource.freebusy().query(body=q_data).execute()

    def get_recent_events(self, cutoff: datetime):
        cal = self._create_resource()
        cutoff_str = cutoff.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        yield from cal.events().list(calendarId=self.admin_email, updatedMin=cutoff_str).execute()['items']

    def create_cal_event(self, *, summary: str, description: str, start: datetime, end: datetime, contact_email: str):
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
        except HttpError as e:
            # TODO: Check if event already exists
            logger.error('Error creating gcal event: %s', e, extra={'event': event})
            raise

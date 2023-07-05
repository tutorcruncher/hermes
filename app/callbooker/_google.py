import logging
from datetime import datetime
from uuid import uuid4

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google.oauth2 import service_account

from ..settings import Settings

settings = Settings()

logger = logging.getLogger('google')


class GoogleCalendar:
    scopes = ['https://www.googleapis.com/auth/calendar']

    def __init__(self, email=None):
        self.email = email

    def create_builder(self):
        creds = service_account.Credentials.from_service_account_info(
            settings.google_credentials, scopes=self.scopes
        ).with_subject(self.email)
        return build('calendar', 'v3', credentials=creds)

    def get_recent_events(self, cutoff: datetime):
        cal = self.create_builder()
        cutoff_str = cutoff.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        yield from cal.events().list(calendarId=self.email, updatedMin=cutoff_str).execute()['items']

    def create_cal_event(self, client: str, company_dict: dict, tc_id: int):
        event = {
            'summary': f'Introduction to TutorCruncher with {client.client_manager.capitalize()}',
            'description': f'''Hi,

Thanks for booking a call with TutorCruncher! We'll be looking forward to seeing you in the Google Meets room!

Please feel free to jot down a few specific questions to discuss with us beforehand, we would really appreciate it. We
 usually find that the most productive conversations are ones in which we can address very specific concerns.

In the meantime, you might find it valuable to glance through some of our documentation which we have prepared to help
 get people familiar with TutorCruncher.

Guided product demo: https://www.youtube.com/watch?v=2iUK0RTm4pw&t=2271s

and here is our user guide for some of our most common questions:
 https://cdn.tutorcruncher.com/guides/admin-user-guide.pdf

If you wish to signup to TutorCruncher to start a two week trial, please click
 <a href="https://secure.tutorcruncher.com/start/1/?cli_id={tc_id}&tc_source=Call_Booker">here.</a>

Looking forward to speaking with you!

Best,
The TutorCruncher Team

Phone Number: {client.phone}
Company Name: {company_dict['name']}
Approximate Monthly Revenue: {client.currency} {client.estimated_income}
''',
            'start': {
                'dateTime': client.meeting_dt,
            },
            'end': {
                'dateTime': datetime.strftime(
                    datetime.strptime(client.meeting_dt, '%Y-%m-%dT%H:%M:%S.%fZ') + relativedelta(minutes=30),
                    '%Y-%m-%dT%H:%M:%S.%fZ',
                ),
            },
            'attendees': [
                {'email': self.email},
                {'email': client.email},
            ],
            'reminders': {
                'useDefault': True,
            },
            'conferenceData': {
                'createRequest': {'requestId': f'{uuid4().hex}', 'conferenceSolutionKey': {'type': 'hangoutsMeet'}}
            },
        }

        cal = self.create_builder()
        try:
            res = (
                cal.events()
                .insert(calendarId=self.email, sendNotifications=True, body=event, conferenceDataVersion=1)
                .execute()
            )
            logger.info(res)
        except HttpError:
            logger.info('Event already exists: %r', event)
            pass

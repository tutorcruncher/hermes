"""The Hermes app for /pr-uat, with Google Calendar pointed at fake_services.py.

The Google client has no base URL setting, so this swaps the one method that builds it. Nothing else differs from
app.main. No service account is used, so a real key can never be read or sent.
"""

import os

from google.auth.credentials import AnonymousCredentials

from app.callbooker import google
from app.main import app

__all__ = ['app']


def _create_resource(self):
    options = {'api_endpoint': os.environ['UAT_GOOGLE_URL']}
    return google.build('calendar', 'v3', credentials=AnonymousCredentials(), client_options=options)


google.AdminGoogleCalendar._create_resource = _create_resource

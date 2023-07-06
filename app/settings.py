from pathlib import Path

from pydantic import BaseSettings, PostgresDsn

THIS_DIR = Path(__file__).parent.resolve()


class Settings(BaseSettings):
    pg_dsn: PostgresDsn = 'postgres://postgres@localhost:5432/hermes'

    support_ttl_days: int = 4
    call_booker_base_url: str = 'https://tutorcruncher.com/book-a-call/'
    meeting_dur_mins: int = 30

    #  TC
    tc2_api_key: str = 'test-key'
    tc2_api_url: str = 'https://localhost:8000/api/'

    # Google
    g_project_id: str = 'tc-hubspot-314214'
    g_client_email: str = 'tc-hubspot@tc-hubspot-314214.iam.gserviceaccount.com'
    g_private_key_id: str = ''
    g_private_key: str = ''
    g_client_id: str = '106687699961269975379'
    g_auth_uri: str = 'https://accounts.google.com/o/oauth2/auth'
    g_token_uri: str = 'https://oauth2.googleapis.com/token'
    g_auth_provider_x509_cert_url: str = 'https://www.googleapis.com/oauth2/v1/certs'
    g_client_x509_cert_url: str = (
        'https://www.googleapis.com/robot/v1/metadata/x509/tc-hubspot%40tc-hubspot-314214.iam.gserviceaccount.com'
    )

    process_google_cal: bool = False

    @property
    def google_credentials(self):
        return {
            'type': 'service_account',
            'project_id': self.g_project_id,
            'private_key_id': self.g_private_key_id,
            'private_key': self.g_private_key.replace('\\n', '\n'),
            'client_email': self.g_client_email,
            'client_id': self.g_client_id,
            'auth_uri': self.g_auth_uri,
            'token_uri': self.g_token_uri,
            'auth_provider_x509_cert_url': self.g_auth_provider_x509_cert_url,
            'client_x509_cert_url': self.g_client_x509_cert_url,
        }

    class Config:
        env_file = '.env'

    # @validator('pg_dsn')
    # def heroku_ready_pg_dsn(cls, v):
    #     return v.replace('gres://', 'gresql://')

from pathlib import Path

from pydantic import BaseSettings, Extra, Field, PostgresDsn, RedisDsn

THIS_DIR = Path(__file__).parent.resolve()


class Settings(BaseSettings):
    pg_dsn: PostgresDsn = Field('postgres://postgres@localhost:5432/hermes', env='DATABASE_URL', alias='database_url')

    # Redis
    redis_dsn: RedisDsn = Field('redis://localhost:6379', env='REDIS_URL', alias='redis_url')

    # Sentry
    sentry_dsn: str = ''

    dft_timezone = 'Europe/London'
    signing_key: str = 'test-key'
    host: str = '0.0.0.0'
    port: int = 8000

    # Dev and Test settings
    testing: bool = True
    dev_mode: bool = False
    log_level: str = 'INFO'

    # Call booker
    callbooker_base_url: str = 'https://tutorcruncher.com/book-a-call'

    # How long a support link is valid for
    support_ttl_days: int = 4

    meeting_dur_mins: int = 30
    meeting_buffer_mins: int = 15
    meeting_min_start: str = '10:00'
    meeting_max_end: str = '17:30'

    #  TC2
    tc2_api_key: str = 'test-key'
    tc2_base_url: str = 'http://localhost:8000'

    # Pipedrive
    pd_api_key: str = '45fc768ccd3e73fbe1925e7849b7471bf64a54ac'
    pd_base_url: str = 'https://seb-sandbox2.pipedrive.com'

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
        extra = Extra.allow

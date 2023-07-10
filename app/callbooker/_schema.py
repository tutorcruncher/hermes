from datetime import datetime
from enum import Enum
from functools import cached_property
from typing import Optional

from pydantic import BaseModel, validator
from pytz import utc


class CBEvent(BaseModel):
    tc_cligency_id: Optional[int]
    name: str
    website: Optional[str]
    email: str
    country: str
    phone_ext: Optional[str]
    phone: Optional[str]
    company_name: str
    estimated_income: str
    currency: str
    client_manager: Optional[int]
    sales_person: Optional[int]
    meeting_dt: datetime
    timezone: str
    form_json: dict = {}

    @validator('name', 'company_name', 'website', 'country')
    def strip(cls, v):
        return v.strip()

    @validator('email')
    def email_to_lower(cls, v):
        return v.lower()

    @validator('name')
    def name_to_title(cls, v):
        return v.title()

    @validator('sales_person', always=True)
    def validate_sales_person_or_client_manager(cls, v, values):
        if not v and not values.get('client_manager'):
            raise ValueError('Either sales_person or client_manager must be provided')
        elif v and values.get('client_manager'):
            raise ValueError('Only one of sales_person or client_manager must be provided')
        return v

    @validator('meeting_dt', pre=True)
    def convert_from_ts(cls, v):
        return datetime.fromtimestamp(v, tz=utc)

    @cached_property
    def _name_split(self):
        return self.name.split(' ', 1)

    @property
    def first_name(self):
        if len(self._name_split) > 1:
            return self._name_split[0]

    @property
    def last_name(self):
        return self._name_split[-1]

    @property
    def meeting_admin(self):
        return self.client_manager or self.sales_person

    def company_dict(self) -> dict:
        return {
            'tc_cligency_id': self.tc_cligency_id,
            'estimated_income': self.estimated_income,
            'currency': self.currency,
            'website': self.website,
            'country': self.country,
            'name': self.company_name,
            'form_json': self.form_json,
        }

    def contact_dict(self) -> dict:
        return {
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'phone': (self.phone_ext or '' + self.phone) if self.phone else None,
            'country': self.country,
        }


class AvailType(str, Enum):
    """
    When showing the booking slots to clients, we generally allow a lead time of at least 2 hours. For support calls,
    we want an "instant" meeting to allow the client to book a meeting immediately.
    """

    INSTANT = 'instant'
    STANDARD = 'standard'


class AvailabilityData(BaseModel):
    admin_id: int
    start_dt: datetime
    end_dt: datetime
    avail_type: AvailType

    @validator('start_dt', 'end_dt', pre=True)
    def convert_from_ts(cls, v):
        return datetime.fromtimestamp(v, tz=utc)

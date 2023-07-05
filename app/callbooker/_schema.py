import time
from datetime import datetime
from functools import cached_property
from typing import Optional

import pytz
from pydantic import BaseModel, validator


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

    @validator('sales_person')
    def validate_sales_person_or_client_manager(cls, v, values):
        if not v and not values.get('client_manager'):
            raise ValueError('Either sales_person or client_manager must be provided')
        return v

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
    def local_start(self) -> datetime:
        return (
            pytz.timezone(self.timezone)
            .localize(self.meeting_dt, is_dst=time.localtime().tm_isdst > 0)
            .astimezone(pytz.timezone('Europe/London'))
        )

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

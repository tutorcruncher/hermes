from datetime import datetime, timezone
from functools import cached_property
from typing import Optional

from pydantic import validator

from app.base_schema import fk_field, HermesBaseModel
from app.models import Company, Admin


def _convert_to_utc(v: datetime) -> datetime:
    if not v.tzinfo:
        v = v.replace(tzinfo=timezone.utc)
    elif v.tzinfo and v.tzinfo != timezone.utc:
        v = v.astimezone(timezone.utc)
    if v <= datetime.now(timezone.utc):
        raise ValueError('meeting_dt must be in the future')
    return v


def _strip(v: str) -> str:
    return v.strip()


def _to_lower(v: str) -> str:
    return v.lower()


def _to_title(v: str) -> str:
    return v.title()


class CBSalesCall(HermesBaseModel):
    admin_id: fk_field(Admin)
    company_id: Optional[fk_field(Company)] = None
    name: str
    website: Optional[str]
    email: str
    country: str
    phone_ext: Optional[str]
    phone: Optional[str]
    company_name: str
    estimated_income: str
    currency: str
    meeting_dt: datetime
    price_plan: str

    _convert_to_utc = validator('meeting_dt', allow_reuse=True)(_convert_to_utc)
    _strip = validator('name', 'company_name', 'website', 'country', allow_reuse=True)(_strip)
    _to_lower = validator('email', allow_reuse=True)(_to_lower)
    _to_title = validator('name', allow_reuse=True)(_to_title)

    @validator('price_plan')
    def _price_plan(cls, v):
        assert v in (Company.PP_PAYG, Company.PP_STARTUP, Company.PP_ENTERPRISE)
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

    async def company_dict(self) -> dict:
        return {
            'sales_person_id': (await self.admin).id,
            'estimated_income': self.estimated_income,
            'currency': self.currency,
            'website': self.website,
            'country': self.country,
            'name': self.company_name,
            'price_plan': self.price_plan,
        }

    async def contact_dict(self) -> dict:
        return {
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'phone': (self.phone_ext or '' + self.phone) if self.phone else None,
            'country': self.country,
        }


class CBSupportCall(HermesBaseModel):
    """
    The schema for data submitted when someone books a support call. Similar to the sales call, and possibly we could
    reuse the code if we wanted to, but I think it's better to keep them separate for now.
    """

    company_id: fk_field(Company)
    admin_id: fk_field(Admin)
    meeting_dt: datetime
    email: str
    name: str
    country: str
    company_name: str

    _convert_to_utc = validator('meeting_dt', allow_reuse=True)(_convert_to_utc)
    _strip = validator('name', allow_reuse=True)(_strip)
    _to_lower = validator('email', allow_reuse=True)(_to_lower)
    _to_title = validator('name', allow_reuse=True)(_to_title)

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

    async def contact_dict(self) -> dict:
        return {
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'country': self.country,
        }

    async def company_dict(self) -> dict:
        return {
            'tc2_cligency_id': self.tc2_cligency_id,
            'country': self.country,
            'name': self.company_name,
            'admin_id': (await self.admin).id,
        }

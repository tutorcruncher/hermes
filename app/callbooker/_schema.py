from datetime import datetime, timezone
from functools import cached_property
from typing import Optional

from pydantic import field_validator

from app.base_schema import HermesBaseModel, ForeignKeyField
from app.models import Admin, Company


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
    admin_id: int = ForeignKeyField(model=Admin)
    bdr_person_id: Optional[int] = ForeignKeyField(None, model=Admin, to_field='bdr')
    utm_campaign: Optional[str] = None
    company_id: Optional[int] = ForeignKeyField(None, model=Company)
    name: str
    website: Optional[str] = None
    email: str
    country: str
    phone: Optional[str] = None
    company_name: str
    estimated_income: str | int
    currency: str
    meeting_dt: datetime
    price_plan: str

    _convert_to_utc = field_validator('meeting_dt')(_convert_to_utc)
    _strip = field_validator('name', 'company_name', 'website', 'country')(_strip)
    _to_lower = field_validator('email')(_to_lower)
    _to_title = field_validator('name')(_to_title)

    @field_validator('price_plan')
    @classmethod
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
            'bdr_person_id': (await self.bdr).id if self.bdr else None,
            'utm_campaign': self.utm_campaign,
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
            'phone': self.phone,
            'country': self.country,
        }


class CBSupportCall(HermesBaseModel):
    """
    The schema for data submitted when someone books a support call. Similar to the sales call, and possibly we could
    reuse the code if we wanted to, but I think it's better to keep them separate for now.
    """

    company_id: int = ForeignKeyField(model=Company)
    admin_id: int = ForeignKeyField(model=Admin)
    meeting_dt: datetime
    email: str
    name: str

    _convert_to_utc = field_validator('meeting_dt')(_convert_to_utc)
    _strip = field_validator('name')(_strip)
    _to_lower = field_validator('email')(_to_lower)
    _to_title = field_validator('name')(_to_title)

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
        return {'first_name': self.first_name, 'last_name': self.last_name, 'email': self.email}

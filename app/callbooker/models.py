from datetime import datetime, timezone
from functools import cached_property
from typing import Optional

from pydantic import BaseModel, field_validator


def _convert_to_utc(v: datetime) -> datetime:
    """Convert datetime to UTC and validate it's in the future"""
    if not v.tzinfo:
        v = v.replace(tzinfo=timezone.utc)
    elif v.tzinfo and v.tzinfo != timezone.utc:
        v = v.astimezone(timezone.utc)
    if v <= datetime.now(timezone.utc):
        raise ValueError('meeting_dt must be in the future')
    return v


def _strip(v: str) -> str:
    return v.strip()


def _to_lower(v: Optional[str]) -> Optional[str]:
    return v.lower() if v else v


def _to_title(v: str) -> str:
    return v.title()


class CBSalesCall(BaseModel):
    """Schema for sales call booking from website"""

    admin_id: int
    bdr_person_id: Optional[int] = None
    utm_campaign: Optional[str] = None
    utm_source: Optional[str] = None
    company_id: Optional[int] = None
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
    _to_lower = field_validator('email', mode='before')(_to_lower)
    _to_title = field_validator('name')(_to_title)

    @field_validator('price_plan')
    @classmethod
    def _price_plan(cls, v):
        valid_plans = ('payg', 'startup', 'enterprise')
        if v not in valid_plans:
            raise ValueError(f'price_plan must be one of {valid_plans}')
        return v

    @cached_property
    def _name_split(self):
        return self.name.split(' ', 1)

    @property
    def first_name(self):
        if len(self._name_split) > 1:
            return self._name_split[0]
        return None

    @property
    def last_name(self):
        return self._name_split[-1]

    def company_dict(self) -> dict:
        """Convert to dict for creating/updating Company"""
        return {
            'sales_person_id': self.admin_id,
            'bdr_person_id': self.bdr_person_id,
            'utm_campaign': self.utm_campaign[:255] if self.utm_campaign else None,
            'utm_source': self.utm_source[:255] if self.utm_source else None,
            'estimated_income': str(self.estimated_income),
            'currency': self.currency,
            'website': self.website[:255] if self.website else None,
            'country': self.country,
            'name': self.company_name[:255],
            'price_plan': self.price_plan,
        }

    def contact_dict(self) -> dict:
        """Convert to dict for creating/updating Contact"""
        return {
            'first_name': self.first_name[:255] if self.first_name else None,
            'last_name': self.last_name[:255] if self.last_name else None,
            'email': self.email[:255] if self.email else None,
            'phone': self.phone[:255] if self.phone else None,
            'country': self.country,
        }


class CBSupportCall(BaseModel):
    """Schema for support call booking from website"""

    company_id: int
    admin_id: int
    meeting_dt: datetime
    email: Optional[str] = None
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
        return None

    @property
    def last_name(self):
        return self._name_split[-1]

    def contact_dict(self) -> dict:
        """Convert to dict for creating/updating Contact"""
        return {
            'first_name': self.first_name[:255] if self.first_name else None,
            'last_name': self.last_name[:255] if self.last_name else None,
            'email': self.email[:255] if self.email else None,
        }

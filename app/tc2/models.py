import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger('tc2')


class TCSubject(BaseModel):
    """A webhook Subject (generally a Client or Invoice)"""

    model: Optional[str] = None
    id: int
    model_config = ConfigDict(extra='allow')


class _TCSimpleRole(BaseModel):
    """Used to parse a role that's used a SimpleRoleSerializer"""

    id: int = Field(exclude=True)
    first_name: Optional[str] = None
    last_name: str


class _TCAgency(BaseModel):
    """TC2 Agency data"""

    id: int = Field(exclude=True)
    name: str
    country: str
    website: Optional[str] = None
    status: str
    paid_invoice_count: int
    created: datetime = Field(exclude=True)
    price_plan: str
    narc: Optional[bool] = False
    signup_questionnaire: Optional[dict] = None
    pay0_dt: Optional[datetime] = None
    pay1_dt: Optional[datetime] = None
    pay3_dt: Optional[datetime] = None
    card_saved_dt: Optional[datetime] = None
    email_confirmed_dt: Optional[datetime] = None
    gclid: Optional[str] = None
    gclid_expiry_dt: Optional[datetime] = None

    @field_validator('price_plan')
    @classmethod
    def _price_plan(cls, v):
        plan = v.split('-')[-1]
        valid_plans = ('payg', 'startup', 'enterprise')
        if plan not in valid_plans:
            plan = 'payg'
            logger.warning(f'Invalid price plan {v}')
        return plan

    @field_validator('country')
    @classmethod
    def country_to_code(cls, v):
        return v.split(' ')[-1].strip('()')


class TCRecipient(_TCSimpleRole):
    """TC2 recipient (contact)"""

    email: Optional[str] = None


class TCUser(BaseModel):
    """TC2 user"""

    email: Optional[str] = None
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: str


class TCClientExtraAttr(BaseModel):
    """TC2 client extra attribute"""

    machine_name: str
    value: str

    @field_validator('value')
    @classmethod
    def validate_value(cls, v):
        return v.strip()

    @model_validator(mode='after')
    def process_value(self):
        # Don't convert GCLID values to lowercase as they are case-sensitive
        if self.machine_name != 'gclid':
            self.value = self.value.lower().strip('-')
        return self


class TCClient(BaseModel):
    """TC2 Client"""

    id: int = Field(exclude=True)
    meta_agency: _TCAgency = Field(exclude=True)
    user: TCUser
    status: str

    sales_person_id: Optional[int] = None
    associated_admin_id: Optional[int] = None
    bdr_person_id: Optional[int] = None

    paid_recipients: list[TCRecipient]
    extra_attrs: Optional[list[TCClientExtraAttr]] = None

    @model_validator(mode='before')
    @classmethod
    def parse_admins(cls, data):
        """Extract admin IDs from nested objects"""
        if associated_admin := data.pop('associated_admin', None):
            data['associated_admin_id'] = associated_admin['id']
        if bdr_person := data.pop('bdr_person', None):
            data['bdr_person_id'] = bdr_person['id']
        if sales_person := data.pop('sales_person', None):
            data['sales_person_id'] = sales_person['id']
        return data

    @model_validator(mode='before')
    @classmethod
    def set_user_email(cls, data):
        """If user has no email, use first paid recipient email"""
        if 'user' in data and not data['user'].get('email'):
            paid_recip_with_email = next((r for r in data['paid_recipients'] if r.get('email')), None)
            if paid_recip_with_email:
                data['user']['email'] = paid_recip_with_email['email']
        return data

    @field_validator('extra_attrs')
    @classmethod
    def remove_null_attrs(cls, v: list[TCClientExtraAttr]):
        return [attr for attr in v if attr.value]


class TCEvent(BaseModel):
    """A TC2 webhook event"""

    action: str
    verb: str
    subject: TCSubject


class TCWebhook(BaseModel):
    """A TC2 webhook"""

    events: list[TCEvent]
    _request_time: int

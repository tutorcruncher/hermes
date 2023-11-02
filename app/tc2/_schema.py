from datetime import datetime
from typing import Optional

from pydantic import field_validator, model_validator, ConfigDict, Field

from app.base_schema import HermesBaseModel, fk_field
from app.models import Admin, Company


class TCSubject(HermesBaseModel):
    """
    A webhook Subject (generally a Client or Invoice)
    """

    model: str
    id: int
    model_config = ConfigDict(extra='allow')


class _TCSimpleRole(HermesBaseModel):
    """
    Used to parse a role that's used a SimpleRoleSerializer
    """

    id: int = Field(exclude=True)
    first_name: Optional[str] = None
    last_name: str


class _TCAgency(HermesBaseModel):
    id: int = Field(exclude=True)
    name: str
    country: str
    website: Optional[str] = None
    status: str
    paid_invoice_count: int
    created: datetime = Field(exclude=True)
    price_plan: str

    @field_validator('price_plan')
    @classmethod
    def _price_plan(cls, v):
        # Extract the part after the hyphen
        plan = v.split('-')[-1]
        # Validate the extracted part
        valid_plans = (Company.PP_PAYG, Company.PP_STARTUP, Company.PP_ENTERPRISE)
        if plan not in valid_plans:
            raise ValueError(f'Invalid price plan {v}')
        return plan

    @field_validator('country')
    @classmethod
    def country_to_code(cls, v):
        return v.split(' ')[-1].strip('()')


class TCRecipient(_TCSimpleRole):
    email: Optional[str] = None

    def contact_dict(self, *args, **kwargs):
        data = super().dict(*args, **kwargs)
        data['tc2_sr_id'] = self.id
        return data


class TCUser(HermesBaseModel):
    email: str
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: str


class TCClientExtraAttr(HermesBaseModel):
    machine_name: str
    value: str

    @field_validator('value')
    @classmethod
    def validate_value(cls, v):
        return v.lower().strip().strip('-')


class TCClient(HermesBaseModel):
    id: int = Field(exclude=True)
    meta_agency: _TCAgency = Field(exclude=True)
    user: TCUser
    status: str
    sales_person_id: Optional[fk_field(Admin, 'tc2_admin_id', alias='sales_person')] = None
    associated_admin_id: Optional[fk_field(Admin, 'tc2_admin_id', alias='support_person')] = None
    bdr_person_id: Optional[fk_field(Admin, 'tc2_admin_id', alias='bdr_person')] = None
    paid_recipients: list[TCRecipient]
    extra_attrs: Optional[list[TCClientExtraAttr]] = None

    @field_validator('extra_attrs')
    @classmethod
    def remove_null_attrs(cls, v: list[TCClientExtraAttr]):
        return [attr for attr in v if attr.value]

    @model_validator(mode='before')
    @classmethod
    def parse_admins(cls, values):
        """
        Since we don't care about the other details on the admin, we can just get the nested IDs and set attributes.
        """
        if associated_admin := values.pop('associated_admin', None):
            values['associated_admin_id'] = associated_admin['id']
        if bdr_person := values.pop('bdr_person', None):
            values['bdr_person_id'] = bdr_person['id']
        if sales_person := values.pop('sales_person', None):
            values['sales_person_id'] = sales_person['id']
        return values

    def company_dict(self):
        return dict(
            tc2_agency_id=self.meta_agency.id,
            tc2_cligency_id=self.id,
            tc2_status=self.meta_agency.status,
            name=self.meta_agency.name,
            country=self.meta_agency.country,
            website=self.meta_agency.website,
            support_person=self.support_person,  # noqa: F821 - Added in validation
            sales_person=self.sales_person,  # noqa: F821 - Added in validation
            bdr_person=self.bdr_person,  # noqa: F821 - Added in validation
            paid_invoice_count=self.meta_agency.paid_invoice_count,
            price_plan=self.meta_agency.price_plan,
        )


class TCInvoice(HermesBaseModel):
    id: int = Field(exclude=True)
    client: _TCSimpleRole


class TCEvent(HermesBaseModel):
    """
    A TC webhook event
    """

    action: str
    verb: str
    subject: TCSubject


class TCWebhook(HermesBaseModel):
    """
    A TC webhook
    """

    events: list[TCEvent]
    _request_time: int

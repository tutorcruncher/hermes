from typing import Optional

from pydantic import validator, root_validator

from app.base_schema import HermesBaseModel, fk_field
from app.models import Admin


class TCSubject(HermesBaseModel):
    """
    A webhook Subject (generally a Client or Invoice)
    """

    model: str
    id: int


class _TCSimpleRole(HermesBaseModel):
    """
    Used to parse a role that's used a SimpleRoleSerializer
    """

    id: int
    first_name: Optional[str] = None
    last_name: str
    email: Optional[str]


class _TCAgency(HermesBaseModel):
    id: int
    name: str
    country: str
    website: Optional[str] = None
    status: str
    paid_invoice_count: int

    @validator('country')
    def country_to_code(cls, v):
        return v.split(' ')[-1].strip('()')


class TCRecipient(_TCSimpleRole):
    def contact_dict(self, *args, **kwargs):
        data = super().dict(*args, **kwargs)
        data['tc2_sr_id'] = data.pop('id')
        return data


class TCClient(HermesBaseModel):
    id: int
    meta_agency: _TCAgency
    status: str
    sales_person_id: Optional[fk_field(Admin, 'tc2_admin_id', alias='sales_person')] = None
    associated_admin_id: Optional[fk_field(Admin, 'tc2_admin_id', alias='support_person')] = None
    bdr_person_id: Optional[fk_field(Admin, 'tc2_admin_id', alias='bdr_person')] = None
    paid_recipients: list[TCRecipient]

    @root_validator(pre=True)
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
            status=self.meta_agency.status,
            name=self.meta_agency.name,
            country=self.meta_agency.country,
            support_person=self.support_person,  # noqa: F821 - Added in validation
            sales_person=self.sales_person,  # noqa: F821 - Added in validation
            bdr_person=self.bdr_person,  # noqa: F821 - Added in validation
            paid_invoice_count=self.meta_agency.paid_invoice_count,
        )


class TCInvoice(HermesBaseModel):
    id: int
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

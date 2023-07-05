from typing import Optional

from pydantic import BaseModel, validator


class TCSubject(BaseModel):
    """
    A webhook Subject (generally a Client or Invoice)
    """

    model: str
    id: int

    class Config:
        extra = 'allow'


class _TCSimpleUser(BaseModel):
    """
    Used to parse a role that's used a SimpleRoleSerializer
    """

    id: int
    first_name: str
    last_name: str
    email: Optional[str]

    class Config:
        extra = 'allow'


class _TCAdmin(_TCSimpleUser):
    pass


class _TCAgency(BaseModel):
    id: int
    name: str
    country: str
    website: str
    status: str
    paid_invoice_count: int

    @validator('country')
    def country_to_code(cls, v):
        return v.split(' ')[-1].strip('()')

    def dict(self, *args, **kwargs):
        raise RuntimeError('Use the TCClient.dict() method instead.')

    class Config:
        extra = 'allow'


class TCRecipient(_TCSimpleUser):
    def dict(self, *args, **kwargs):
        data = super().dict(*args, **kwargs)
        data['tc_sr_id'] = data.pop('id')
        return data


class TCClient(BaseModel):
    id: int
    meta_agency: _TCAgency
    status: str
    associated_admin: Optional[_TCAdmin]
    sales_person: Optional[_TCAdmin]
    bdr_person: Optional[_TCAdmin]
    paid_recipients: list[TCRecipient]

    def dict(self):
        return dict(
            tc_agency_id=self.meta_agency.id,
            tc_cligency_id=self.id,
            status=self.meta_agency.status,
            name=self.meta_agency.name,
            country=self.meta_agency.country,
            client_manager=self.associated_admin and self.associated_admin.id,
            sales_person=self.sales_person and self.sales_person.id,
            bdr_person=self.bdr_person and self.bdr_person.id,
            paid_invoice_count=self.meta_agency.paid_invoice_count,
        )

    class Config:
        extra = 'allow'


class TCInvoice(BaseModel):
    id: int
    accounting_id: str
    client: _TCSimpleUser

    class Config:
        extra = 'allow'


class TCEvent(BaseModel):
    """
    A TC webhook event
    """

    action: str
    verb: str
    subject: TCSubject

    class Config:
        extra = 'allow'


class TCWebhook(BaseModel):
    """
    A TC webhook
    """

    events: list[TCEvent]
    _request_time: int

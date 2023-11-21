import logging
from datetime import datetime
from typing import Optional

from pydantic import field_validator, model_validator, ConfigDict, Field

from app.base_schema import HermesBaseModel, ForeignKeyField
from app.models import Admin, Company, CustomField

logger = logging.getLogger('tc2')


class TCSubject(HermesBaseModel):
    """
    A webhook Subject (generally a Client or Invoice)
    """

    model: Optional[str] = None
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
            plan = Company.PP_PAYG
            logger.warning(f'Invalid price plan {v}')
        return plan

    @field_validator('country')
    @classmethod
    def country_to_code(cls, v):
        return v.split(' ')[-1].strip('()')


class TCRecipient(_TCSimpleRole):
    email: Optional[str] = None

    def contact_dict(self, *args, **kwargs):
        data = super().model_dump(*args, **kwargs)
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

    sales_person_id: Optional[int] = ForeignKeyField(
        None, model=Admin, fk_field_name='tc2_admin_id', to_field='sales_person'
    )
    associated_admin_id: Optional[int] = ForeignKeyField(
        None, model=Admin, fk_field_name='tc2_admin_id', to_field='support_person'
    )
    bdr_person_id: Optional[int] = ForeignKeyField(
        None, model=Admin, fk_field_name='tc2_admin_id', to_field='bdr_person'
    )

    paid_recipients: list[TCRecipient]
    extra_attrs: Optional[list[TCClientExtraAttr]] = None

    @model_validator(mode='before')
    @classmethod
    def parse_admins(cls, data):
        """
        Since we don't care about the other details on the admin, we can just get the nested IDs and set attributes.
        """
        if associated_admin := data.pop('associated_admin', None):
            data['associated_admin_id'] = associated_admin['id']
        if bdr_person := data.pop('bdr_person', None):
            data['bdr_person_id'] = bdr_person['id']
        if sales_person := data.pop('sales_person', None):
            data['sales_person_id'] = sales_person['id']
        return data

    @field_validator('extra_attrs')
    @classmethod
    def remove_null_attrs(cls, v: list[TCClientExtraAttr]):
        return [attr for attr in v if attr.value]

    async def custom_field_values(self, custom_fields: list['CustomField']) -> dict:
        """
        When updating a Hermes Company from a TCClient,, we need to get the custom field values from the `extra_attrs`
        on the TCClient.
        """
        cf_val_lu = {}
        for cf in [c for c in custom_fields if not c.hermes_field_name]:
            if extra_attr := next((ea for ea in self.extra_attrs if ea.machine_name == cf.tc2_machine_name), None):
                cf_val_lu[cf.id] = extra_attr.value
        return cf_val_lu

    def company_dict(self, custom_fields: list[CustomField]) -> dict:
        cf_data_from_hermes = {}
        for cf in [c for c in custom_fields if c.hermes_field_name and c.field_type != CustomField.TYPE_FK_FIELD]:
            if extra_attr := next((ea for ea in self.extra_attrs if ea.machine_name == cf.tc2_machine_name), None):
                cf_data_from_hermes[cf.hermes_field_name] = extra_attr.value
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
            **cf_data_from_hermes,
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

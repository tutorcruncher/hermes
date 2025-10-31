from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP, CONTACT_PD_FIELD_MAP, DEAL_PD_FIELD_MAP


class _HermesModel(BaseModel):
    @model_validator(mode='before')
    @classmethod
    def flatten_custom_fields(cls, data: Any) -> Any:
        """
        Flatten Pipedrive v2 webhook custom_fields structure.

        Pipedrive v2 sends: {'field_id': {'type': 'varchar', 'value': 'actual_value'}}
        We need: {'field_id': 'actual_value'}
        """
        if isinstance(data, dict) and 'custom_fields' in data:
            custom_fields = data.get('custom_fields', {})
            if isinstance(custom_fields, dict):
                flattened = {}
                for field_id, field_data in custom_fields.items():
                    if isinstance(field_data, dict) and 'value' in field_data:
                        flattened[field_id] = field_data['value']
                    else:
                        flattened[field_id] = field_data
                data.update(flattened)
        return data


class Organisation(_HermesModel):
    """Pipedrive Organization schema - uses centralized field mapping"""

    id: Optional[int] = None
    name: Optional[str] = None
    address_country: Optional[str] = Field(default=None, validation_alias='address_country')
    owner_id: Optional[int] = None

    # Custom fields - reference the centralized mapping
    # hermes_id can be string when Pipedrive merges entities (e.g., "123, 456")
    hermes_id: Optional[int | str] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['hermes_id'])
    paid_invoice_count: Optional[int | str] = Field(
        default=0, validation_alias=COMPANY_PD_FIELD_MAP['paid_invoice_count']
    )
    tc2_cligency_url: Optional[str] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['tc2_cligency_url'])
    tc2_status: Optional[str] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['tc2_status'])
    website: Optional[str] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['website'])
    price_plan: Optional[str] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['price_plan'])
    estimated_income: Optional[str] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['estimated_income'])
    support_person_id: Optional[int] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['support_person_id'])
    bdr_person_id: Optional[int] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['bdr_person_id'])
    signup_questionnaire: Optional[str] = Field(
        default=None, validation_alias=COMPANY_PD_FIELD_MAP['signup_questionnaire']
    )
    utm_source: Optional[str] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['utm_source'])
    utm_campaign: Optional[str] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['utm_campaign'])
    created: Optional[date] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['created'])
    pay0_dt: Optional[date] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['pay0_dt'])
    pay1_dt: Optional[date] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['pay1_dt'])
    pay3_dt: Optional[date] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['pay3_dt'])
    gclid: Optional[str] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['gclid'])
    gclid_expiry_dt: Optional[date] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['gclid_expiry_dt'])
    email_confirmed_dt: Optional[date] = Field(
        default=None, validation_alias=COMPANY_PD_FIELD_MAP['email_confirmed_dt']
    )
    card_saved_dt: Optional[date] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['card_saved_dt'])

    model_config = ConfigDict(populate_by_name=True)


class Person(_HermesModel):
    """Pipedrive Person schema - uses centralized field mapping"""

    id: Optional[int] = None
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = Field(default=None, validation_alias='emails')
    phone: Optional[str] = Field(default=None, validation_alias='phones')
    owner_id: Optional[int] = None
    org_id: Optional[int] = None

    # Custom fields - reference the centralized mapping
    # hermes_id can be string when Pipedrive merges entities (e.g., "123, 456")
    hermes_id: Optional[int | str] = Field(default=None, validation_alias=CONTACT_PD_FIELD_MAP['hermes_id'])

    @model_validator(mode='after')
    def parse_name(self) -> 'Person':
        """
        Parse name field into first_name and last_name.
        Pipedrive sends full name in 'name' field, we split it for internal use.
        """
        if self.name and not self.first_name and not self.last_name:
            name_parts = self.name[:255].split(' ', 1)
            if len(name_parts) > 1:
                self.first_name = name_parts[0][:255]
                self.last_name = name_parts[1][:255]
            else:
                self.last_name = name_parts[0][:255]
        return self

    @field_validator('email', mode='before')
    @classmethod
    def normalize_email(cls, v: Any) -> Optional[str]:
        """
        Normalize email field to string.
        Pipedrive v2 webhooks send arrays of objects with value/label/primary.
        We normalize to a simple string (first email) for internal use.
        """
        if v is None or v == []:
            return None
        if isinstance(v, list) and len(v) > 0:
            if isinstance(v[0], dict) and 'value' in v[0]:
                return v[0]['value']
            if isinstance(v[0], str):
                return v[0]
        if isinstance(v, str):
            return v
        return None

    @field_validator('phone', mode='before')
    @classmethod
    def normalize_phone(cls, v: Any) -> Optional[str]:
        """
        Normalize phone field to string.
        Pipedrive v2 webhooks send arrays of objects with value/label/primary.
        We normalize to a simple string (first phone number) for internal use.
        """
        if v is None:
            return None
        if isinstance(v, list) and len(v) > 0:
            if isinstance(v[0], dict) and 'value' in v[0]:
                return v[0]['value']
            if isinstance(v[0], str):
                return v[0]
        if isinstance(v, str):
            return v
        # This should never be reached with valid Pydantic types
        return None

    model_config = ConfigDict(populate_by_name=True)


class PDDeal(_HermesModel):
    """Pipedrive Deal schema - uses centralized field mapping"""

    id: Optional[int] = None
    title: Optional[str] = None
    person_id: Optional[int] = None
    org_id: Optional[int] = None
    user_id: Optional[int] = Field(default=None, validation_alias='owner_id')
    pipeline_id: Optional[int] = None
    stage_id: Optional[int] = None
    status: Optional[str] = None

    # Custom fields - reference the centralized mapping
    # hermes_id can be string when Pipedrive merges entities (e.g., "123, 456")
    hermes_id: Optional[int | str] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['hermes_id'])
    support_person_id: Optional[int] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['support_person_id'])
    tc2_cligency_url: Optional[str] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['tc2_cligency_url'])
    signup_questionnaire: Optional[str] = Field(
        default=None, validation_alias=DEAL_PD_FIELD_MAP['signup_questionnaire']
    )
    utm_campaign: Optional[str] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['utm_campaign'])
    utm_source: Optional[str] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['utm_source'])
    bdr_person_id: Optional[int] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['bdr_person_id'])
    paid_invoice_count: Optional[int | str] = Field(default=0, validation_alias=DEAL_PD_FIELD_MAP['paid_invoice_count'])
    tc2_status: Optional[str] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['tc2_status'])
    website: Optional[str] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['website'])
    price_plan: Optional[str] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['price_plan'])
    estimated_income: Optional[str] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['estimated_income'])

    model_config = ConfigDict(populate_by_name=True)


class Activity(_HermesModel):
    """Pipedrive Activity schema for creating calendar events"""

    id: Optional[int] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    subject: Optional[str] = None
    user_id: Optional[int] = None
    deal_id: Optional[int] = None
    person_id: Optional[int] = None
    org_id: Optional[int] = None

    model_config = ConfigDict(populate_by_name=True)


class PDPipeline(_HermesModel):
    """Pipedrive Pipeline schema"""

    id: Optional[int] = None
    name: Optional[str] = None
    active: Optional[bool] = None

    model_config = ConfigDict(populate_by_name=True)


class PDStage(_HermesModel):
    """Pipedrive Stage schema"""

    id: Optional[int] = None
    name: Optional[str] = None
    pipeline_id: Optional[int] = None

    model_config = ConfigDict(populate_by_name=True)


class WebhookMeta(BaseModel):
    """Webhook metadata"""

    action: str
    entity: str


class PipedriveEvent(BaseModel):
    """Pipedrive webhook event (v2)"""

    meta: WebhookMeta
    data: Optional[dict] = None
    previous: Optional[dict] = None

    model_config = ConfigDict(populate_by_name=True)

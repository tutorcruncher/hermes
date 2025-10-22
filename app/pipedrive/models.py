from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP, CONTACT_PD_FIELD_MAP, DEAL_PD_FIELD_MAP


class Organisation(BaseModel):
    """Pipedrive Organization schema - uses centralized field mapping"""

    id: Optional[int] = None
    name: Optional[str] = None
    address_country: Optional[str] = Field(default=None, validation_alias='address_country')
    owner_id: Optional[int] = None

    # Custom fields - reference the centralized mapping
    # hermes_id can be string when Pipedrive merges entities (e.g., "123, 456")
    hermes_id: Optional[int | str] = Field(default=None, validation_alias=COMPANY_PD_FIELD_MAP['hermes_id'])
    paid_invoice_count: Optional[int] = Field(default=0, validation_alias=COMPANY_PD_FIELD_MAP['paid_invoice_count'])
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


class Person(BaseModel):
    """Pipedrive Person schema - uses centralized field mapping"""

    id: Optional[int] = None
    name: Optional[str] = None
    email: Optional[list[str]] = None
    phone: Optional[str] = None
    owner_id: Optional[int] = None
    org_id: Optional[int] = None

    # Custom fields - reference the centralized mapping
    # hermes_id can be string when Pipedrive merges entities (e.g., "123, 456")
    hermes_id: Optional[int | str] = Field(default=None, validation_alias=CONTACT_PD_FIELD_MAP['hermes_id'])

    @field_validator('email', mode='before')
    @classmethod
    def normalize_email(cls, v: Any) -> Optional[list[str]]:
        """
        Normalize email field to list of strings.
        Pipedrive v2 webhooks send arrays of objects with value/label/primary.
        We normalize to simple list of strings for internal use.
        """
        if v is None or v == []:
            return []
        if isinstance(v, list):
            if all(isinstance(item, dict) and 'value' in item for item in v):
                return [item['value'] for item in v]
            if all(isinstance(item, str) for item in v):
                return v
        return v

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


class PDDeal(BaseModel):
    """Pipedrive Deal schema - uses centralized field mapping"""

    id: Optional[int] = None
    title: Optional[str] = None
    person_id: Optional[int] = None
    org_id: Optional[int] = None
    user_id: Optional[int] = None
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
    paid_invoice_count: Optional[int] = Field(default=0, validation_alias=DEAL_PD_FIELD_MAP['paid_invoice_count'])
    tc2_status: Optional[str] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['tc2_status'])
    website: Optional[str] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['website'])
    price_plan: Optional[str] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['price_plan'])
    estimated_income: Optional[str] = Field(default=None, validation_alias=DEAL_PD_FIELD_MAP['estimated_income'])

    model_config = ConfigDict(populate_by_name=True)


class Activity(BaseModel):
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


class PDPipeline(BaseModel):
    """Pipedrive Pipeline schema"""

    id: Optional[int] = None
    name: Optional[str] = None
    active: Optional[bool] = None

    model_config = ConfigDict(populate_by_name=True)


class PDStage(BaseModel):
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
    """Pipedrive webhook event"""

    meta: WebhookMeta
    current: Optional[dict] = None
    previous: Optional[dict] = None

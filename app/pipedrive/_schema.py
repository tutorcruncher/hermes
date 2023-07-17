import asyncio
from typing import Optional

from pydantic import BaseModel, Field, root_validator
from tortoise.exceptions import DoesNotExist

from app.models import Companies, Contacts, Deals, Meetings, Pipelines, PipelineStages, Admins


def _remove_nulls(**kwargs):
    return {k: v for k, v in kwargs.items() if v is not None}


def fk_field(model, fk_field_name='pk'):
    class ForeignKeyField(int):
        @classmethod
        def model(cls):
            return model

        @classmethod
        def fk_field_name(cls):
            return fk_field_name

    return ForeignKeyField


class HermesBaseModel(BaseModel):
    async def __new__(cls, *args, **kwargs):
        debug('foo')

    @root_validator(pre=False)
    def fk_validator(cls, values: dict) -> dict:
        for field_name, field in cls.__fields__.items():
            if field.type_.__name__ == 'ForeignKeyField':
                v = values.get(field_name)
                model = field.type_.model()
                field_name = field.type_.fk_field_name()
                try:
                    obj = asyncio.create_task(model.get(**{field_name: v}))
                except DoesNotExist:
                    raise ValueError(f'{model.__name__} with {field_name}={v} does not exist')
                else:
                    values[model.__name__.lower().rstrip('s')] = obj
        return values


class Organisation(HermesBaseModel):
    id: Optional[int] = None
    name: str
    address_country: Optional[str] = None
    owner_id: fk_field(Admins, 'pd_owner_id')

    # These are all custom fields
    estimated_income: str = ''
    status: str = ''
    website: str = ''
    paid_invoice_count: int = 0
    has_booked_call: bool = False
    has_signed_up: bool = False
    tc_profile_url: str = ''

    @classmethod
    async def from_company(cls, company: Companies):
        return cls(
            **_remove_nulls(
                name=company.name,
                owner_id=(await company.sales_person).pd_owner_id,
                address_country=company.country,
                paid_invoice_count=company.paid_invoice_count,
                estimated_income=company.estimated_income,
                currency=company.currency,
                website=company.website,
                status=company.status,
                has_booked_call=company.has_booked_call,
                has_signed_up=company.has_signed_up,
                tc_profile_url=company.tc_cligency_url,
            )
        )

    async def company_dict(self) -> dict:
        return {
            'pd_org_id': self.id,
            'name': self.name,
            'status': self.status,
            'website': self.website,
            'sales_person_id': self.owner_id,
        }


class Person(BaseModel):
    id: Optional[int] = None
    first_name: str
    last_name: str
    owner_id: Optional[int] = None
    email: Optional[str] = Field(alias='primary_email', default=None)
    phone: Optional[str] = None
    address_country: Optional[str] = None
    org_id: Optional[fk_field(Companies, 'pd_org_id')] = None

    @classmethod
    async def from_contact(cls, contact: Contacts):
        company: Companies = await contact.company
        return cls(
            first_name=contact.first_name,
            last_name=contact.last_name,
            owner_id=company.sales_person_id and (await company.sales_person).pd_owner_id,
            email=contact.email,
            phone=contact.phone,
            address_country=contact.country,
            org_id=company.pd_org_id,
        )

    async def contact_dict(self) -> dict:
        # We ignore phone here, as it comes through as {'label': 'phone', 'value': '123456789'}
        return {
            'pd_person_id': self.id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
        }


class Activity(BaseModel):
    due_dt: str
    due_time: str
    subject: str
    user_id: int
    deal_id: Optional[int] = None
    person_id: Optional[int] = None
    org_id: Optional[int] = None

    @classmethod
    async def from_meeting(cls, meeting: Meetings):
        contact = await meeting.contact
        return cls(
            **_remove_nulls(
                **{
                    'due_dt': meeting.start_time.strftime('%Y-%m-%d'),
                    'due_time': meeting.start_time.strftime('%H:%M'),
                    'subject': meeting.name,
                    'user_id': (await meeting.admin).pd_owner_id,
                    'deal_id': meeting.deal_id and (await meeting.deal).pd_deal_id,
                    'person_id': contact.pd_person_id,
                    'org_id': (await contact.company).pd_org_id,
                }
            )
        )


class PDDeal(BaseModel):
    id: Optional[int] = None
    title: str
    org_id: int
    person_id: Optional[int] = None
    pipeline_id: fk_field(Pipelines, 'pd_pipeline_id')
    stage_id: fk_field(PipelineStages, 'pd_stage_id')
    status: str

    @classmethod
    async def from_deal(cls, deal: Deals):
        company = deal.company_id and await deal.company
        contact = deal.contact_id and await deal.contact
        pipeline = await deal.pipeline
        pipeline_stage = await deal.pipeline_stage
        return cls(
            **_remove_nulls(
                title=deal.name,
                org_id=company and company.pd_org_id,
                user_id=(await deal.admin).pd_owner_id,
                person_id=contact and contact.pd_person_id,
                pipeline_id=pipeline.pd_pipeline_id,
                stage_id=pipeline_stage.pd_stage_id,
                status=deal.status,
            )
        )

    async def deal_dict(self) -> dict:
        return {
            'pd_deal_id': self.id,
            'name': self.title,
            'status': self.status,
            'person_id': self.person_id,
            'pd_org_id': self.org_id,
            'pd_pipeline_id': self.pipeline_id,
            'pd_stage_id': self.stage_id,
        }


class PDPipeline(BaseModel):
    id: int
    name: str

    async def pipeline_dict(self):
        return {'pd_pipeline_id': self.id, 'name': self.name}


class PDStage(BaseModel):
    id: fk_field(PipelineStages, 'pd_stage_id')
    name: str

    async def stage_dict(self):
        return {'pd_stage_id': self.id, 'name': self.name}


class WebhookMeta(BaseModel):
    action: str
    object: str


class PipedriveEvent(BaseModel):
    # We validate the current and previous dicts in the webhook handler
    current: dict
    previous: dict
    meta: WebhookMeta

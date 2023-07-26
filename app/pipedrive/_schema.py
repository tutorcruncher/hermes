from typing import Optional

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, Extra, validator
from tortoise.exceptions import DoesNotExist

from app.models import Company, Contact, Deal, Meeting, Pipeline, Stage, Admin


def _remove_nulls(**kwargs):
    return {k: v for k, v in kwargs.items() if v is not None}


def fk_field(model, fk_field_name='pk'):
    class ForeignKeyField(int):
        """
        A custom field type for Pydantic that allows us to validate a foreign key by querying the db using the
        a_validate method below.
        """

        @classmethod
        def model(cls):
            return model

        @classmethod
        def fk_field_name(cls):
            return fk_field_name

    return ForeignKeyField


class HermesBaseModel(BaseModel, extra=Extra.allow):
    async def a_validate(self):
        """
        Validates any ForeignKeys on the model by querying the db.
        Annoyingly, we can't do this in Pydantic's built in validation as it doesn't support async validators.
        """
        for field_name, field in self.__fields__.items():
            if field.type_.__name__ == 'ForeignKeyField':
                v = self.dict().get(field_name)
                model = field.type_.model()
                field_name = field.type_.fk_field_name()
                try:
                    related_obj = await model.get(**{field_name: v})
                except DoesNotExist:
                    raise RequestValidationError(
                        [
                            {
                                'loc': [field.name],
                                'msg': f'{model.__name__} with {field_name} {v} does not exist',
                                'type': 'value_error',
                            }
                        ]
                    )
                else:
                    setattr(self, model.__name__.lower(), related_obj)


class Organisation(HermesBaseModel):
    id: Optional[int] = None
    name: str
    address_country: Optional[str] = None
    owner_id: fk_field(Admin, 'pd_owner_id')

    # These are all custom fields
    estimated_income: str = ''
    status: str = ''
    website: str = ''
    paid_invoice_count: int = 0
    has_booked_call: bool = False
    has_signed_up: bool = False
    tc_profile_url: str = ''

    @classmethod
    async def from_company(cls, company: Company):
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
            'sales_person_id': self.admin.id,  # noqa: F821 - Added in validation
        }


class Person(HermesBaseModel):
    id: Optional[int] = None
    first_name: str
    last_name: str
    email: Optional[str] = Field(alias='primary_email', default=None)
    phone: Optional[str] = None
    address_country: Optional[str] = None
    org_id: Optional[fk_field(Company, 'pd_org_id')] = None

    @classmethod
    async def from_contact(cls, contact: Contact):
        company: Company = await contact.company
        return cls(
            first_name=contact.first_name,
            last_name=contact.last_name,
            owner_id=company.sales_person_id and (await company.sales_person).pd_owner_id,
            email=contact.email,
            phone=contact.phone,
            address_country=contact.country,
            org_id=company.pd_org_id,
        )

    @validator('phone', 'email', pre=True)
    def get_primary_attr(cls, v):
        """
        When coming in from a webhook, phone and email are lists of dicts so we need to get the primary one.
        """
        if isinstance(v, list):
            item = next((i for i in v if i['primary']), v[0])
            v = item['value']
        return v

    async def contact_dict(self) -> dict:
        return {
            'pd_person_id': self.id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'phone': self.phone,
            'company_id': self.company.id,  # noqa: F821 - Added in validation
        }


class Activity(HermesBaseModel):
    due_dt: str
    due_time: str
    subject: str
    user_id: int
    deal_id: Optional[int] = None
    person_id: Optional[int] = None
    org_id: Optional[int] = None

    @classmethod
    async def from_meeting(cls, meeting: Meeting):
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


class PDDeal(HermesBaseModel):
    id: Optional[int] = None
    title: str
    org_id: int
    person_id: Optional[fk_field(Contact, 'pd_person_id')] = None
    org_id: fk_field(Company, 'pd_org_id')
    user_id: fk_field(Admin, 'pd_owner_id')
    pipeline_id: fk_field(Pipeline, 'pd_pipeline_id')
    stage_id: fk_field(Stage, 'pd_stage_id')
    status: str

    @classmethod
    async def from_deal(cls, deal: Deal):
        company = deal.company_id and await deal.company
        contact = deal.contact_id and await deal.contact
        pipeline = await deal.pipeline
        stage = await deal.stage
        return cls(
            **_remove_nulls(
                title=deal.name,
                org_id=company and company.pd_org_id,
                user_id=(await deal.admin).pd_owner_id,
                person_id=contact and contact.pd_person_id,
                pipeline_id=pipeline.pd_pipeline_id,
                stage_id=stage.pd_stage_id,
                status=deal.status,
            )
        )

    async def deal_dict(self) -> dict:
        return {
            'pd_deal_id': self.id,
            'name': self.title,
            'status': self.status,
            'admin_id': self.admin.id,  # noqa: F821 - Added in validation
            'company_id': self.company.id,  # noqa: F821 - Added in validation
            'contact_id': self.contact and self.company.id,  # noqa: F821 - Added in validation
            'pipeline_id': self.pipeline.id,  # noqa: F821 - Added in validation
            'stage_id': self.stage.id,  # noqa: F821 - Added in validation
        }


class PDPipeline(HermesBaseModel):
    id: int
    name: str
    active: bool

    async def pipeline_dict(self):
        return {'pd_pipeline_id': self.id, 'name': self.name}


class PDStage(HermesBaseModel):
    id: int
    name: str
    pipeline_id: int

    async def stage_dict(self):
        return {'pd_stage_id': self.id, 'name': self.name}


class WebhookMeta(HermesBaseModel):
    action: str
    object: str


class PipedriveEvent(HermesBaseModel):
    # We validate the current and previous dicts below depending on the object type
    meta: WebhookMeta
    current: Optional[PDDeal | Person | Organisation | PDPipeline | PDStage] = None
    previous: Optional[PDDeal | Person | Organisation | PDPipeline | PDStage] = None

    @validator('current', 'previous', pre=True)
    def validate_current_previous(cls, v, values):
        if v:
            match values['meta'].object:
                case 'deal':
                    return PDDeal(**v)
                case 'person':
                    return Person(**v)
                case 'organization':
                    return Organisation(**v)
                case 'pipeline':
                    return PDPipeline(**v)
                case 'stage':
                    return PDStage(**v)
                case _:
                    return v

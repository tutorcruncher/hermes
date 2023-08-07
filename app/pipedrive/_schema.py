import json
from typing import Optional, ClassVar, Literal

from pydantic import Field, validator, root_validator
from pydantic.fields import ModelField
from pydantic.main import BaseModel, validate_model

from app.base_schema import fk_field, HermesBaseModel
from app.models import Company, Contact, Deal, Meeting, Pipeline, Stage, Admin
from app.utils import get_redis_client


def _remove_nulls(**kwargs):
    return {k: v for k, v in kwargs.items() if v is not None}


def _slugify(name: str) -> str:
    return name.lower().replace(' ', '_')


def _get_obj_id(v) -> str | int:
    if isinstance(v, dict):
        return v['value']
    return v


class PDFieldOption(BaseModel):
    id: int
    label: str


class PDExtraField(BaseModel):
    key: str
    name: str
    options: list[PDFieldOption] = None

    @property
    def machine_name(self):
        return _slugify(self.name)


class PipedriveBaseModel(HermesBaseModel):
    """
    All of this logic is basically here to deal with Pipedrive's horrible custom fields.
    """

    @classmethod
    async def _custom_fields(cls) -> dict[str, ModelField]:
        """Get all fields that have the 'custom' attribute"""
        return {n: f for n, f in cls.__fields__.items() if f.field_info.extra.get('custom')}

    @classmethod
    async def _get_pd_custom_fields(cls) -> dict[str, PDExtraField]:
        """
        Gets the custom fields from Pipedrive that match to the custom fields on the model. This is cached for 5 minutes
        """
        from app.pipedrive.api import pipedrive_request

        cache_key = f'{cls.custom_fields_pd_name}-custom-fields'
        redis = await get_redis_client()
        if cached_pd_fields_data := await redis.get(cache_key):
            pd_fields_data = json.loads(cached_pd_fields_data)
        else:
            pd_fields_data = (await pipedrive_request(cls.custom_fields_pd_name))['data']
            await redis.set(cache_key, json.dumps(pd_fields_data), ex=300)
        field_lu = {}
        custom_fields = await cls._custom_fields()
        for pd_field in pd_fields_data:
            if custom_field := custom_fields.get(_slugify(pd_field['name'])):
                field_lu[custom_field.name] = PDExtraField(**pd_field)
        return field_lu

    @classmethod
    async def set_custom_field_vals(cls, obj: 'PipedriveBaseModel') -> 'PipedriveBaseModel':
        # TODO: Move to post_model_init in v2
        custom_field_lu = await cls._get_pd_custom_fields()
        for field_name, pd_field in custom_field_lu.items():
            field = cls.__fields__[field_name]
            field.alias = pd_field.key

        # Since we've set the field aliases, we can just re-validate the model to add the values
        validate_model(obj.__class__, obj.__dict__)

        return obj

    class Config:
        allow_population_by_field_name = True


class Organisation(PipedriveBaseModel):
    id: Optional[int] = Field(None, exclude=True)
    name: str
    address_country: Optional[str] = None
    owner_id: fk_field(Admin, 'pd_owner_id')

    # These are all custom fields
    website: Optional[str] = Field('', custom=True)
    paid_invoice_count: Optional[int] = Field(0, custom=True)
    has_booked_call: Optional[bool] = Field(False, custom=True)
    has_signed_up: Optional[bool] = Field(False, custom=True)
    tc2_status: Optional[str] = Field('', custom=True)
    tc2_cligency_url: Optional[str] = Field('', custom=True)

    _get_obj_id = validator('owner_id', allow_reuse=True, pre=True)(_get_obj_id)
    custom_fields_pd_name: ClassVar[str] = 'organizationFields'
    obj_type: Literal['organization'] = Field('organization', exclude=True)

    @classmethod
    async def from_company(cls, company: Company) -> 'Organisation':
        obj = cls(
            **_remove_nulls(
                name=company.name,
                owner_id=(await company.sales_person).pd_owner_id,
                address_country=company.country,
                website=company.website,
                paid_invoice_count=company.paid_invoice_count,
                has_booked_call=company.has_booked_call,
                has_signed_up=company.has_signed_up,
                tc2_status=company.tc2_status,
                tc2_cligency_url=company.tc2_cligency_url,
            )
        )
        obj = await cls.set_custom_field_vals(obj)
        return obj

    async def company_dict(self) -> dict:
        return {
            'pd_org_id': self.id,
            'name': self.name,
            'tc2_status': self.tc2_status,
            'website': self.website,
            'sales_person_id': self.admin.id,  # noqa: F821 - Added in validation
        }


class Person(PipedriveBaseModel):
    id: Optional[int] = Field(None, exclude=True)
    name: str
    primary_email: Optional[str] = ''
    phone: Optional[str] = ''
    address_country: Optional[str] = None
    owner_id: Optional[fk_field(Admin, 'pd_owner_id')] = None
    org_id: Optional[fk_field(Company, 'pd_org_id')] = None

    _get_obj_id = validator('org_id', 'owner_id', allow_reuse=True, pre=True)(_get_obj_id)
    obj_type: Literal['person'] = Field('person', exclude=True)

    @classmethod
    async def from_contact(cls, contact: Contact):
        company: Company = await contact.company
        return cls(
            name=contact.name,
            owner_id=company.sales_person_id and (await company.sales_person).pd_owner_id,
            primary_email=contact.email,
            phone=contact.phone,
            address_country=contact.country,
            org_id=company.pd_org_id,
        )

    @validator('phone', pre=True)
    def get_primary_attr(cls, v):
        """
        When coming in from a webhook, phone and email are lists of dicts so we need to get the primary one.
        """
        if isinstance(v, list):
            item = next((i for i in v if i['primary']), v[0])
            v = item['value']
        return v

    async def contact_dict(self) -> dict:
        name_parts = self.name.split(' ', 1)
        first_name = None
        if len(name_parts) > 1:
            first_name = name_parts[0]
        last_name = name_parts[-1]
        return {
            'pd_person_id': self.id,
            'first_name': first_name,
            'last_name': last_name,
            'email': self.primary_email,
            'phone': self.phone,
            'company_id': self.company.id,  # noqa: F821 - Added in validation
        }


class Activity(PipedriveBaseModel):
    id: Optional[int] = Field(None, exclude=True)
    due_dt: str
    due_time: str
    subject: str
    user_id: int
    deal_id: Optional[int] = None
    person_id: Optional[int] = None
    org_id: Optional[int] = None
    obj_type: Literal['activity'] = Field('activity', exclude=True)

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


class PDDeal(PipedriveBaseModel):
    id: Optional[int] = Field(None, exclude=True)
    title: str
    org_id: int
    person_id: Optional[fk_field(Contact, 'pd_person_id')] = None
    org_id: fk_field(Company, 'pd_org_id')
    user_id: fk_field(Admin, 'pd_owner_id')
    pipeline_id: fk_field(Pipeline, 'pd_pipeline_id')
    stage_id: fk_field(Stage, 'pd_stage_id')
    status: str
    obj_type: Literal['deal'] = Field('deal', exclude=True)

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


class PDPipeline(PipedriveBaseModel):
    id: int
    name: str
    active: bool
    obj_type: Literal['pipeline'] = Field('pipeline', exclude=True)

    async def pipeline_dict(self):
        return {'pd_pipeline_id': self.id, 'name': self.name}


class PDStage(PipedriveBaseModel):
    id: int
    name: str
    pipeline_id: int
    obj_type: Literal['stage'] = Field('stage', exclude=True)

    async def stage_dict(self):
        return {'pd_stage_id': self.id, 'name': self.name}


class PDGeneric(BaseModel):
    obj_type: Literal['generic'] = Field('generic', exclude=True)

    def __bool__(self):
        return False


class WebhookMeta(HermesBaseModel):
    action: str
    object: str


class PipedriveEvent(HermesBaseModel):
    # We validate the current and previous dicts below depending on the object type
    meta: WebhookMeta
    current: Optional[PDDeal | PDStage | Person | Organisation | PDPipeline | PDGeneric] = Field(
        None, discriminator='obj_type'
    )
    previous: Optional[PDDeal | PDStage | Person | Organisation | PDPipeline | PDGeneric] = Field(
        None, discriminator='obj_type'
    )

    @root_validator(pre=True)
    def validate_object_type(cls, values):
        obj_type = values['meta']['object']
        for f in ['current', 'previous']:
            if v := values.get(f):
                v['obj_type'] = obj_type
            else:
                values[f] = {'obj_type': 'generic'}
        return values
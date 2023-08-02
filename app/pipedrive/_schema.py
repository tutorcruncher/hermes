import json
from dataclasses import dataclass
from typing import Optional, ClassVar, Literal

from pydantic import Field, validator, Extra, root_validator
from pydantic.main import BaseModel, object_setattr
from tortoise.fields import BooleanField

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


@dataclass
class PDFieldOption:
    id: int
    label: str


class PDExtraField(BaseModel):
    key: str
    name: str
    options: list[PDFieldOption] = None

    @property
    def machine_name(self):
        return _slugify(self.name)


class PipedriveBaseModel(HermesBaseModel, extra=Extra.allow):
    """
    All of this logic is basically here to deal with Pipedrive's horrible custom fields.
    """

    @classmethod
    async def _custom_field_names(cls) -> list[str]:
        """Get all fields that have the 'custom' attribute"""
        return [f for f in cls.__fields__.keys() if cls.__fields__[f].field_info.extra.get('custom')]

    @classmethod
    async def _get_pd_custom_fields(cls) -> list[PDExtraField]:
        """
        Gets the custom fields from Pipedrive that match to the custom fields on the model. This is cached for 5 minutes
        """
        from app.pipedrive.api import pipedrive_request

        cache_key = f'{cls.custom_fields_pd_name}-custom-fields'
        redis = await get_redis_client()
        if fields_data := await redis.get(cache_key):
            return [PDExtraField(**field) for field in json.loads(fields_data)]
        else:
            pd_fields = (await pipedrive_request(cls.custom_fields_pd_name))['data']
            fields = []
            custom_field_names = await cls._custom_field_names()
            for pd_field in pd_fields:
                if _slugify(pd_field['name']) in custom_field_names:
                    field = PDExtraField(**pd_field)
                    fields.append(field)
            await redis.set(cache_key, json.dumps([f.dict() for f in fields]), ex=300)
            return fields

    @classmethod
    async def _parse_pd_custom_field_vals(cls, hermes_obj: Company) -> dict:
        """
        Generates the key/values for pushing custom field data to Pipedrive. The 'key' is got from doing a request to
        get extra fields and is usually a random number/letter string. Pipedrive doesn't use BooleanFields, so we have
        to parse them to Yes or blank values.
        """
        pd_custom_fields = await cls._get_pd_custom_fields()
        extra_field_data = {}
        hermes_obj_fields = hermes_obj._meta.fields_map
        for field in pd_custom_fields:
            if field.machine_name in await cls._custom_field_names():
                val = getattr(hermes_obj, field.machine_name)
                if field.options:
                    # If the field in Hermes is a BooleanField, we have to match it to the correct option in Pipedrive
                    if isinstance(hermes_obj_fields[field.machine_name], BooleanField) and val is True:
                        val = 'Yes'
                extra_field_data[field.key] = val
        return extra_field_data

    @classmethod
    async def set_custom_field_vals(cls, obj: 'PipedriveBaseModel', company: Company = None) -> 'PipedriveBaseModel':
        custom_field_vals = _remove_nulls(**await cls._parse_pd_custom_field_vals(company))
        for field, val in custom_field_vals.items():
            object_setattr(obj, field, val)
        return obj


class Organisation(PipedriveBaseModel):
    id: Optional[int] = Field(None, exclude=True)
    name: str
    address_country: Optional[str] = None
    owner_id: fk_field(Admin, 'pd_owner_id')

    # These are all custom fields
    website: str = Field('', exclude=True, custom=True)
    paid_invoice_count: int = Field(0, exclude=True, custom=True)
    has_booked_call: bool = Field(False, exclude=True, custom=True)
    has_signed_up: bool = Field(False, exclude=True, custom=True)
    tc2_status: str = Field('', exclude=True, custom=True)
    tc2_cligency_url: str = Field('', exclude=True, custom=True)

    _get_obj_id = validator('owner_id', allow_reuse=True, pre=True)(_get_obj_id)
    custom_fields_pd_name: ClassVar[str] = 'organizationFields'
    obj_type: Literal['organization']

    @classmethod
    async def from_company(cls, company: Company) -> 'Organisation':
        obj = cls(
            **_remove_nulls(
                name=company.name,
                owner_id=(await company.sales_person).pd_owner_id,
                address_country=company.country,
            )
        )
        obj = await cls.set_custom_field_vals(obj, company)
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
    obj_type: Literal['person']

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
    obj_type: Literal['activity']

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
    obj_type: Literal['deal']

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
    obj_type: Literal['pipeline']

    async def pipeline_dict(self):
        return {'pd_pipeline_id': self.id, 'name': self.name}


class PDStage(PipedriveBaseModel):
    id: int
    name: str
    pipeline_id: int
    obj_type: Literal['stage']

    async def stage_dict(self):
        return {'pd_stage_id': self.id, 'name': self.name}


class PDGeneric(BaseModel):
    obj_type: Literal['generic']

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

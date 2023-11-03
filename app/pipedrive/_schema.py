import json
import re
from typing import ClassVar, Literal, Optional, Any

from pydantic import field_validator, model_validator, ConfigDict, Field
from pydantic.main import BaseModel

from app.base_schema import HermesBaseModel, ForeignKeyField
from app.models import Admin, Company, Contact, Deal, Meeting, Pipeline, Stage
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
    def _custom_fields(cls) -> list[str]:
        """Get all fields that have the 'custom' attribute"""
        return [n for n, f in cls.model_fields.items() if f.json_schema_extra and f.json_schema_extra.get('custom')]

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
        custom_fields = cls._custom_fields()
        for pd_field in pd_fields_data:
            field_name = _slugify(pd_field['name'])
            if field_name in custom_fields:
                field_lu[field_name] = PDExtraField(**pd_field)
        return field_lu

    @classmethod
    async def set_custom_field_vals(cls, obj: 'PipedriveBaseModel') -> 'PipedriveBaseModel':
        # TODO: Move to post_model_init?
        custom_field_lu = await cls._get_pd_custom_fields()
        for field_name, pd_field in custom_field_lu.items():
            field = cls.model_fields[field_name]
            field.serialization_alias = pd_field.key

        # Since we've set the field aliases, we now need to rebuild the schema for the model.
        cls.model_rebuild(force=True)
        obj = cls(**obj.__dict__)
        return obj

    async def a_validate(self):
        # We need to set the custom field values before we validate
        if self._custom_fields():
            await self.__class__.set_custom_field_vals(self)
        await super().a_validate()

    model_config = ConfigDict(populate_by_name=True)


class Organisation(PipedriveBaseModel):
    id: Optional[int] = Field(None, exclude=True)
    name: str
    address_country: Optional[str] = None
    owner_id: int = ForeignKeyField(model=Admin, fk_field_name='pd_owner_id')

    # These are all custom fields
    website: Optional[str] = Field('', json_schema_extra={'custom': True})
    paid_invoice_count: Optional[int] = Field(0, json_schema_extra={'custom': True})
    has_booked_call: Optional[bool] = Field(False, json_schema_extra={'custom': True})
    has_signed_up: Optional[bool] = Field(False, json_schema_extra={'custom': True})
    tc2_status: Optional[str] = Field('', json_schema_extra={'custom': True})
    tc2_cligency_url: Optional[str] = Field('', json_schema_extra={'custom': True})
    hermes_id: Optional[int] = ForeignKeyField(None, model=Company, custom=True)

    _get_obj_id = field_validator('owner_id', mode='before')(_get_obj_id)

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
                hermes_id=company.id,
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
            'sales_person_id': self.admin.id,  # noqa: F821 - Added in a_validate
        }


# Used to get only alphanumeric characters & whitespace for client entering phone numbers
PHONE_RE = re.compile(r'[^A-Za-z0-9\s]')


class Person(PipedriveBaseModel):
    id: Optional[int] = Field(None, exclude=True)
    name: str
    email: Optional[str] = ''
    phone: Optional[str] = ''
    owner_id: Optional[int] = ForeignKeyField(None, model=Admin, fk_field_name='pd_owner_id')
    org_id: Optional[int] = ForeignKeyField(None, model=Company, fk_field_name='pd_org_id', null_if_invalid=True)

    # These are all custom fields
    hermes_id: Optional[int] = ForeignKeyField(None, model=Contact, custom=True)

    _get_obj_id = field_validator('org_id', 'owner_id', mode='before')(_get_obj_id)
    custom_fields_pd_name: ClassVar[str] = 'personFields'
    obj_type: Literal['person'] = Field('person', exclude=True)

    @classmethod
    async def from_contact(cls, contact: Contact):
        company: Company = await contact.company
        obj = cls(
            name=contact.name,
            owner_id=company.sales_person_id and (await company.sales_person).pd_owner_id,
            email=contact.email,
            phone=contact.phone,
            org_id=company.pd_org_id,
            hermes_id=contact.id,
        )
        obj = await cls.set_custom_field_vals(obj)
        return obj

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """
        This is really annoying; it seems the only way to post `email` is as a list of strs.
        """
        data = super().model_dump(**kwargs)
        data['email'] = [data['email']]
        return data

    @field_validator('phone', 'email', mode='before')
    @classmethod
    def get_primary_attr(cls, v):
        """
        When coming in from a webhook, email is a list of dicts where one is the 'primary'.
        Apparently data can apparently come in 3 formats:
        'email': [{'label': 'work', 'value': '1234567890', 'primary': True}]
        'email': '1234567890'
        'email': ['1234567890']
        TODO: Check that this is True
        """
        if not v:
            return
        if isinstance(v, list):
            if isinstance(v[0], dict):
                item = next((i for i in v if i['primary']), v[0])
                v = item['value']
            elif isinstance(v[0], str):
                v = v[0]
        else:
            assert isinstance(v, str)
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
            'email': self.email,
            'phone': self.phone,
            'company_id': self.company and self.company.id,  # noqa: F821 - Added in a_validate
        }


class Activity(PipedriveBaseModel):
    id: Optional[int] = Field(None, exclude=True)
    due_date: str
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
                    'due_date': meeting.start_time.strftime('%Y-%m-%d'),
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
    person_id: Optional[int] = ForeignKeyField(None, model=Contact, fk_field_name='pd_person_id', null_if_invalid=True)
    org_id: int = ForeignKeyField(model=Company, fk_field_name='pd_org_id')
    user_id: int = ForeignKeyField(model=Admin, fk_field_name='pd_owner_id')
    pipeline_id: int = ForeignKeyField(model=Pipeline, fk_field_name='pd_pipeline_id')
    stage_id: int = ForeignKeyField(model=Stage, fk_field_name='pd_stage_id')
    status: str

    # These are all custom fields
    hermes_id: Optional[int] = ForeignKeyField(None, model=Deal, null_if_invalid=True, custom=True)

    _get_obj_id = field_validator('user_id', 'person_id', 'org_id', mode='before')(_get_obj_id)
    custom_fields_pd_name: ClassVar[str] = 'dealFields'
    obj_type: Literal['deal'] = Field('deal', exclude=True)

    @classmethod
    async def from_deal(cls, deal: Deal):
        company = deal.company_id and await deal.company
        contact = deal.contact_id and await deal.contact
        pipeline = await deal.pipeline
        stage = await deal.stage
        obj = cls(
            **_remove_nulls(
                title=deal.name,
                org_id=company and company.pd_org_id,
                user_id=(await deal.admin).pd_owner_id,
                person_id=contact and contact.pd_person_id,
                pipeline_id=pipeline.pd_pipeline_id,
                stage_id=stage.pd_stage_id,
                hermes_id=deal.id,
                status=deal.status,
            )
        )
        obj = await cls.set_custom_field_vals(obj)
        return obj

    async def deal_dict(self) -> dict:
        return {
            'pd_deal_id': self.id,
            'name': self.title,
            'status': self.status,
            'admin_id': self.admin.id,  # noqa: F821 - Added in a_validate
            'company_id': self.company.id,  # noqa: F821 - Added in a_validate
            'contact_id': self.contact and self.contact.id,  # noqa: F821 - Added in a_validate
            'pipeline_id': self.pipeline.id,  # noqa: F821 - Added in a_validate
            'stage_id': self.stage.id,  # noqa: F821 - Added in a_validate
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


class WebhookMeta(HermesBaseModel):
    action: str
    object: str


class PipedriveEvent(HermesBaseModel):
    # We validate the current and previous dicts below depending on the object type
    meta: WebhookMeta
    current: Optional[PDDeal | PDStage | Person | Organisation | PDPipeline] = Field(None, discriminator='obj_type')
    previous: Optional[PDDeal | PDStage | Person | Organisation | PDPipeline] = Field(None, discriminator='obj_type')

    @model_validator(mode='before')
    @classmethod
    def validate_object_type(cls, values):
        obj_type = values['meta']['object']
        for f in ['current', 'previous']:
            if v := values.get(f):
                v['obj_type'] = obj_type
            else:
                values.pop(f, None)
        return values

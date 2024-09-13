import re
from enum import Enum
from typing import Any, List, Literal, Optional, Union

import logfire
from pydantic import Field, field_validator, model_validator
from pydantic.main import BaseModel

from app.base_schema import ForeignKeyField, HermesBaseModel
from app.models import Admin, Company, Contact, CustomField, Deal, Meeting, Pipeline, Stage
from app.pipedrive._utils import app_logger


class PDStatus(str, Enum):
    PREVIOUS = 'previous'
    CURRENT = 'current'


class PDObjectNames(str, Enum):
    ORGANISATION = 'organization'
    PERSON = 'person'
    DEAL = 'deal'
    PIPELINE = 'pipeline'
    STAGE = 'stage'
    ACTIVITY = 'activity'


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
    async def custom_field_values(self, custom_fields: list['CustomField']) -> dict:
        """
        When updating a Hermes model from a Pipedrive webhook, we need to get the custom field values from the
        Pipedrive model.
        """
        custom_field_values = {}

        for custom_field in custom_fields:
            if not custom_field.hermes_field_name:
                value = getattr(self, custom_field.machine_name)
                custom_field_values[custom_field.id] = value

        return custom_field_values


class Organisation(PipedriveBaseModel):
    id: Optional[int] = Field(None, exclude=True)
    name: str
    address_country: Optional[str] = None
    owner_id: Optional[int] = ForeignKeyField(None, model=Admin, fk_field_name='pd_owner_id')

    _get_obj_id = field_validator('owner_id', mode='before')(_get_obj_id)

    obj_type: Literal['organization'] = Field('organization', exclude=True)

    @classmethod
    async def from_company(cls, company: Company) -> 'Organisation':
        cls_kwargs = dict(
            name=company.name,
            owner_id=(await company.sales_person).pd_owner_id,
            tc2_status=company.tc2_status,
            tc2_cligency_url=company.tc2_cligency_url,
            address_country=company.country,
        )
        cls_kwargs.update(await cls.get_custom_field_vals(company))
        final_kwargs = _remove_nulls(**cls_kwargs)
        return cls(**final_kwargs)

    async def company_dict(self, custom_fields: list[CustomField]) -> dict:
        cf_data_from_hermes = {
            c.hermes_field_name: getattr(self, c.machine_name)
            for c in custom_fields
            if c.hermes_field_name and c.field_type != CustomField.TYPE_FK_FIELD
        }

        admins_from_hermes = {}
        if hasattr(self, 'support_person') and self.support_person:
            if isinstance(self.support_person, int):
                self.support_person = await Admin.get(id=self.support_person)
            admins_from_hermes['support_person_id'] = self.support_person.id

        if hasattr(self, 'bdr_person') and self.bdr_person:
            if isinstance(self.bdr_person, int):
                self.bdr_person = await Admin.get(id=self.bdr_person)
            admins_from_hermes['bdr_person_id'] = self.bdr_person.id

        return {
            'pd_org_id': self.id,
            'name': self.name,
            'sales_person_id': self.admin.id,  # noqa: F821 - Added in a_validate
            **_remove_nulls(**cf_data_from_hermes),
            **_remove_nulls(**admins_from_hermes),
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

    _get_obj_id = field_validator('org_id', 'owner_id', mode='before')(_get_obj_id)
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
            **await cls.get_custom_field_vals(contact),
        )
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
        # need to ensure we dont have to await the admin twice
        admin = await meeting.admin
        meeting.admin = admin
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

    _get_obj_id = field_validator('user_id', 'person_id', 'org_id', mode='before')(_get_obj_id)
    obj_type: Literal['deal'] = Field('deal', exclude=True)

    @classmethod
    async def from_deal(cls, deal: Deal):
        company = deal.company_id and await deal.company
        contact = deal.contact_id and await deal.contact
        pipeline = await deal.pipeline
        stage = await deal.stage

        cls_kwargs = dict(
            title=deal.name,
            org_id=company.pd_org_id,
            user_id=(await deal.admin).pd_owner_id,
            person_id=contact and contact.pd_person_id,
            pipeline_id=pipeline.pd_pipeline_id,
            stage_id=stage.pd_stage_id,
            status=deal.status,
        )
        cls_kwargs.update(await cls.get_custom_field_vals(deal))
        final_kwargs = _remove_nulls(**cls_kwargs)
        return cls(**final_kwargs)

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


async def update_and_delete_objects(
    objects: List[Union[Company, Contact, Deal]], main_object: Union[Company, Contact, Deal], object_type: str
):
    """
    @param objects: a list of objects to update, can be either Company, Contact or Deal
    @param main_object: the object to keep
    @param object_type: the type of object we are dealing with
    @return:    None
    """
    for obj in objects:
        if object_type == PDObjectNames.ORGANISATION:
            contacts = await Contact.filter(company=obj)
            for contact in contacts:
                contact.company = main_object
                await contact.save()

            deals = await Deal.filter(company=obj)
            for deal in deals:
                deal.company = main_object
                await deal.save()

        elif object_type == PDObjectNames.PERSON:
            deals = await Deal.filter(contact=obj)
            for deal in deals:
                deal.contact = main_object
                await deal.save()

            meetings = await Meeting.filter(contact=obj)
            for meeting in meetings:
                meeting.contact = main_object
                await meeting.save()

        elif object_type == PDObjectNames.DEAL:
            meetings = await Meeting.filter(deal=obj)
            for meeting in meetings:
                meeting.deal = main_object
                await meeting.save()

        if obj.id != main_object.id:
            await obj.delete()


async def handle_duplicate_hermes_ids(hermes_ids: str, object_type: str) -> int:
    """
    @param hermes_ids: a string of comma-separated hermes IDs
    @param object_type: the type of object we are dealing with
    @return: a single hermes ID
    """
    from app.pipedrive.api import pipedrive_request

    with logfire.span('handle_duplicate_hermes_ids:%s of type %s' % (hermes_ids, object_type)):
        if ',' in hermes_ids:
            hermes_ids_list = hermes_ids.split(',')
        else:
            hermes_ids_list = [hermes_ids]

        if object_type == PDObjectNames.ORGANISATION:
            objects = await Company.filter(id__in=hermes_ids_list)
        elif object_type == PDObjectNames.PERSON:
            objects = await Contact.filter(id__in=hermes_ids_list)
        elif object_type == PDObjectNames.DEAL:
            objects = await Deal.filter(id__in=hermes_ids_list)
        else:
            raise ValueError(f'Unknown object type {object_type}')

        main_object = objects[0]
        await update_and_delete_objects(objects, main_object, object_type)
        # update the hermes_id field of the main object in Pipedrive
        if object_type == PDObjectNames.ORGANISATION:
            if main_object.pd_org_id:
                hermes_org = await Organisation.from_company(main_object)
                hermes_org_data = hermes_org.model_dump(by_alias=True)
                await pipedrive_request(f'organizations/{main_object.pd_org_id}', method='PUT', data=hermes_org_data)
                app_logger.info(
                    f'Updated org {main_object.pd_org_id} from company {main_object.id} by company.pd_org_id'
                )

        elif object_type == PDObjectNames.PERSON:
            if main_object.pd_person_id:
                hermes_person = await Person.from_contact(main_object)
                hermes_person_data = hermes_person.model_dump(by_alias=True)
                await pipedrive_request(f'persons/{main_object.pd_person_id}', method='PUT', data=hermes_person_data)
                app_logger.info(
                    f'Updated person {main_object.pd_person_id} from contact {main_object.id} by contact.pd_person_id'
                )

        elif object_type == PDObjectNames.DEAL:
            if main_object.pd_deal_id:
                hermes_deal = await PDDeal.from_deal(main_object)
                hermes_deal_data = hermes_deal.model_dump(by_alias=True)
                await pipedrive_request(f'deals/{main_object.pd_deal_id}', method='PUT', data=hermes_deal_data)
                app_logger.info(f'Updated deal {main_object.pd_deal_id} from deal {main_object.id} by deal.pd_deal_id')



        # we should actually break here, as if we continue, we will be updating with the incorrect data, and we have just updated, which should in turn trigger the webhook again

        else:
            raise ValueError(f'Unknown object type {object_type}')


class PipedriveEvent(HermesBaseModel):
    # We validate the current and previous dicts below depending on the object type
    meta: WebhookMeta
    current: Optional[PDDeal | PDStage | Person | Organisation | PDPipeline] = None
    previous: Optional[PDDeal | PDStage | Person | Organisation | PDPipeline] = None

    @model_validator(mode='before')
    @classmethod
    def validate_object_type(cls, values):
        obj_type = values['meta']['object']
        for f in [PDStatus.CURRENT, PDStatus.PREVIOUS]:
            if v := values.get(f):
                v['obj_type'] = obj_type
            else:
                values.pop(f, None)
        return values

    @field_validator(PDStatus.CURRENT, PDStatus.PREVIOUS, mode='before')
    @classmethod
    def validate_obj(cls, v) -> Organisation | Person | PDDeal | PDPipeline | PDStage | Activity:
        """
        It would be nice to use Pydantic's discrimators here, but FastAPI won't change the model validation after we
        rebuild the model when adding custom fields.
        """
        if v['obj_type'] == PDObjectNames.ORGANISATION:
            return Organisation(**v)
        elif v['obj_type'] == PDObjectNames.PERSON:
            return Person(**v)
        elif v['obj_type'] == PDObjectNames.DEAL:
            return PDDeal(**v)
        elif v['obj_type'] == PDObjectNames.PIPELINE:
            return PDPipeline(**v)
        elif v['obj_type'] == PDObjectNames.STAGE:
            return PDStage(**v)
        elif v['obj_type'] == PDObjectNames.ACTIVITY:
            return Activity(**v)
        else:
            raise ValueError(f'Unknown object type {v["obj_type"]}')

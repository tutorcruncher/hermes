import re
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic.main import BaseModel
from tortoise.exceptions import DoesNotExist

from app.base_schema import ForeignKeyField, HermesBaseModel
from app.models import Admin, Company, Contact, CustomField, Deal, Meeting, Pipeline, Stage
from app.pipedrive._utils import app_logger


class PDStatus(str, Enum):
    PREVIOUS = 'previous'
    DATA = 'data'


class PDObjectNames(str, Enum):
    # Entities we process (all others are ignored in callback)
    ORGANISATION = 'organization'
    PERSON = 'person'
    DEAL = 'deal'
    PIPELINE = 'pipeline'
    STAGE = 'stage'
    # Entities we don't process but need enum values for
    ACTIVITY = 'activity'  # Used for creating calendar events, not processed from webhooks
    NOTE = 'note'  # Not processed


def _clean_for_pd(**kwargs) -> dict:
    data = {}
    for k, v in kwargs.items():
        if v is None:
            continue
        elif isinstance(v, datetime):
            v = v.date().isoformat()
        elif isinstance(v, date):
            v = v.isoformat()
        data[k] = v
    return data


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
    @model_validator(mode='before')
    @classmethod
    def handle_merged_hermes_id(cls, values):
        """
        Handle cases where Pipedrive merges organizations/persons/deals and the hermes_id custom field
        becomes a comma-separated list like "55839, 53670". We extract the highest ID (most recent).
        """
        if not isinstance(values, dict):
            return values

        for field_name, field_info in cls.model_fields.items():
            if field_name == 'hermes_id':
                # Found the hermes_id field, pd_field_id from the validation_alias
                field_key = (
                    field_info.validation_alias
                    if hasattr(field_info, 'validation_alias') and field_info.validation_alias
                    else field_name
                )

                if field_key in values and isinstance(values[field_key], str) and ',' in values[field_key]:
                    try:
                        original_value = values[field_key]
                        ids = [int(id.strip()) for id in original_value.split(',')]
                        max_id = max(ids)
                        values[field_key] = max_id
                        app_logger.info(
                            f'Merged hermes_id detected in {field_key}: "{original_value}" -> keeping highest ID: {max_id}'
                        )
                    except (ValueError, AttributeError):
                        pass
                break  # Only one hermes_id field, we're done

        return values

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
    name: Optional[str] = None
    address_country: Optional[str] = None
    owner_id: Optional[int] = ForeignKeyField(None, model=Admin, fk_field_name='pd_owner_id')
    created: Optional[date] = None
    pay0_dt: Optional[date] = None
    pay1_dt: Optional[date] = None
    pay3_dt: Optional[date] = None
    gclid: Optional[str] = None
    gclid_expiry_dt: Optional[date] = None
    email_confirmed_dt: Optional[date] = None
    card_saved_dt: Optional[date] = None

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
            pay0_dt=company.pay0_dt,
            pay1_dt=company.pay1_dt,
            pay3_dt=company.pay3_dt,
            gclid=company.gclid,
            gclid_expiry_dt=company.gclid_expiry_dt,
            email_confirmed_dt=company.email_confirmed_dt,
            card_saved_dt=company.card_saved_dt,
            created=company.created,
        )
        cls_kwargs.update(await cls.get_custom_field_vals(company))
        final_kwargs = _clean_for_pd(**cls_kwargs)
        return cls(**final_kwargs)

    async def company_dict(self, custom_fields: list[CustomField]) -> dict:
        cf_data_from_hermes = {
            c.hermes_field_name: value
            for c in custom_fields
            if c.hermes_field_name
            and c.field_type != CustomField.TYPE_FK_FIELD
            and (value := getattr(self, c.machine_name)) is not None
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

        return _clean_for_pd(
            pd_org_id=self.id,
            name=self.name,
            sales_person_id=self.admin.id if self.admin else None,  # noqa: F821 - Added in a_validate
            **cf_data_from_hermes,
            **admins_from_hermes,
        )


# Used to get only alphanumeric characters & whitespace for client entering phone numbers
PHONE_RE = re.compile(r'[^A-Za-z0-9\s]')


class Person(PipedriveBaseModel):
    id: Optional[int] = Field(None, exclude=True)
    name: Optional[str] = None
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
        first_name = None
        last_name = None
        if self.name:
            name_parts = self.name.split(' ', 1)
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
    """
    Activity model for creating calendar events in Pipedrive.
    Note: Activity webhooks are ignored in callback() and not processed through PipedriveEvent.
    """

    id: Optional[int] = Field(None, exclude=True)
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    subject: Optional[str] = None
    user_id: Optional[int] = None
    deal_id: Optional[int] = None
    person_id: Optional[int] = None
    org_id: Optional[int] = None
    obj_type: Literal['activity'] = Field('activity', exclude=True)

    @field_validator('due_time', 'due_date', mode='before')
    @classmethod
    def extract_value_from_dict(cls, v):
        """
        Extract value from Pipedrive's time/date dict format when receiving webhooks.
        Pipedrive can send time/date as: {'timezone_id': None, 'value': '17:30:00'}
        or as a plain string: '17:30:00'
        For v1 API, we send simple strings, but webhooks may still use dict format.
        """
        if isinstance(v, dict) and 'value' in v:
            return v['value']
        return v

    @classmethod
    async def from_meeting(cls, meeting: Meeting):
        contact = await meeting.contact
        # need to ensure we dont have to await the admin twice
        admin = await meeting.admin
        meeting.admin = admin
        return cls(
            **_clean_for_pd(
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
    title: Optional[str] = None
    person_id: Optional[int] = ForeignKeyField(None, model=Contact, fk_field_name='pd_person_id', null_if_invalid=True)
    org_id: Optional[int] = ForeignKeyField(None, model=Company, fk_field_name='pd_org_id')
    user_id: Optional[int] = ForeignKeyField(None, model=Admin, fk_field_name='pd_owner_id')
    pipeline_id: Optional[int] = ForeignKeyField(None, model=Pipeline, fk_field_name='pd_pipeline_id')
    stage_id: Optional[int] = ForeignKeyField(None, model=Stage, fk_field_name='pd_stage_id')
    status: Optional[str] = None

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
        final_kwargs = _clean_for_pd(**cls_kwargs)
        return cls(**final_kwargs)

    async def deal_dict(self) -> dict:
        return _clean_for_pd(
            pd_deal_id=self.id,
            name=self.title,
            status=self.status,
            admin_id=self.admin.id if self.admin else None,  # noqa: F821 - Added in a_validate
            company_id=self.company.id if self.company else None,  # noqa: F821 - Added in a_validate
            contact_id=self.contact and self.contact.id,  # noqa: F821 - Added in a_validate
            pipeline_id=self.pipeline.id if self.pipeline else None,  # noqa: F821 - Added in a_validate
            stage_id=self.stage.id if self.stage else None,  # noqa: F821 - Added in a_validate
        )


class PDPipeline(PipedriveBaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    active: Optional[bool] = None
    obj_type: Literal['pipeline'] = Field('pipeline', exclude=True)

    async def pipeline_dict(self):
        return {'pd_pipeline_id': self.id, 'name': self.name}


class PDStage(PipedriveBaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    pipeline_id: Optional[int] = None
    obj_type: Literal['stage'] = Field('stage', exclude=True)

    async def stage_dict(self):
        return {'pd_stage_id': self.id, 'name': self.name}


class WebhookMeta(HermesBaseModel):
    action: str
    entity: str


async def handle_duplicate_hermes_ids(hermes_ids: str, object_type: str, pipedrive_id: int) -> int:
    """
    Handles cases where Pipedrive organizations are merged and hermes_id becomes a comma-separated list.
    When Pipedrive merges entities, the primary one keeps its ID. We find the Hermes object linked to
    that Pipedrive ID and update Pipedrive to contain only that object's hermes_id.

    @param hermes_ids: a string of comma-separated hermes IDs or a single ID
    @param object_type: the type of object we are dealing with (organization, person, or deal)
    @param pipedrive_id: the Pipedrive ID of the primary entity (org_id, person_id, or deal_id)
    @return: the hermes ID of the object linked to the pipedrive_id
    """
    from app.pipedrive.api import pipedrive_request

    # Find the Hermes object linked to this Pipedrive entity
    try:
        if object_type == PDObjectNames.ORGANISATION:
            hermes_object = await Company.get(pd_org_id=pipedrive_id)
            pd_endpoint = f'organizations/{pipedrive_id}'
        elif object_type == PDObjectNames.PERSON:
            hermes_object = await Contact.get(pd_person_id=pipedrive_id)
            pd_endpoint = f'persons/{pipedrive_id}'
        elif object_type == PDObjectNames.DEAL:
            hermes_object = await Deal.get(pd_deal_id=pipedrive_id)
            pd_endpoint = f'deals/{pipedrive_id}'
        else:
            raise ValueError(f'Unknown object type {object_type}')
    except DoesNotExist:
        # If we can't find the object, just return the first ID from the list
        app_logger.warning(f'Could not find {object_type} with Pipedrive ID {pipedrive_id}, using first hermes_id')
        if ',' in hermes_ids:
            return int(hermes_ids.split(',')[0].strip())
        return int(hermes_ids)

    # Update Pipedrive to have only this object's hermes_id
    if object_type == PDObjectNames.ORGANISATION:
        hermes_schema = await Organisation.from_company(hermes_object)
    elif object_type == PDObjectNames.PERSON:
        hermes_schema = await Person.from_contact(hermes_object)
    elif object_type == PDObjectNames.DEAL:
        hermes_schema = await PDDeal.from_deal(hermes_object)

    hermes_data = hermes_schema.model_dump(by_alias=True)
    await pipedrive_request(pd_endpoint, method='PUT', data=hermes_data)

    app_logger.info(f'Updated {object_type} {pipedrive_id} to have hermes_id={hermes_object.id} (was: {hermes_ids})')
    return hermes_object.id


class PipedriveEvent(HermesBaseModel):
    meta: WebhookMeta
    data: Optional[PDDeal | PDStage | Person | Organisation | PDPipeline] = None
    previous: Optional[PDDeal | PDStage | Person | Organisation | PDPipeline] = None

    @model_validator(mode='before')
    @classmethod
    def validate_object_type(cls, values):
        obj_type = values['meta']['entity']
        for f in [PDStatus.DATA, PDStatus.PREVIOUS]:
            if v := values.get(f):
                v['obj_type'] = obj_type
            else:
                values.pop(f, None)
        return values

    @field_validator(PDStatus.DATA, PDStatus.PREVIOUS, mode='before')
    @classmethod
    def validate_obj(cls, v) -> Organisation | Person | PDDeal | PDPipeline | PDStage:
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
        else:
            raise ValueError(f'Unknown object type {v["obj_type"]}')

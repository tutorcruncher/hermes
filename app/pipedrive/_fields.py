import json
from dataclasses import dataclass

from pydantic import BaseModel
from tortoise.fields import BooleanField

from app.models import Company
from app.pipedrive.api import pipedrive_request
from app.utils import get_redis_client


class PDFieldOption(BaseModel):
    id: int
    label: str


class PDExtraField(BaseModel):
    key: str
    name: str
    field_type: str
    options: list[PDFieldOption] = None

    @property
    def machine_name(self):
        return self.name.lower().replace(' ', '_')


async def parse_extra_field_values(fields: list[PDExtraField], obj: Company) -> dict:
    """
    Generates the key/values for pushing custom field data to Pipedrive. The key is got from doing a request to get the
    extra fields and is usually a random number/letter string. Pipedrive doesn't use BooleanFields, so we have to parse
    them to Yes or blank values.
    """
    extra_field_data = {}
    obj_field_names = list(obj._meta.fields_map.keys())
    for field in fields:
        if field.machine_name in obj_field_names:
            val = getattr(obj, field.machine_name)
            if field.options:
                # If the field in Hermes is a BooleanField, we have to match it to the correct option in Pipedrive
                if isinstance(obj._meta.fields_map[field.machine_name], BooleanField) and val is True:
                    val = 'Yes'
            extra_field_data[field.key] = val
    return extra_field_data


async def get_org_custom_fields() -> list[PDExtraField]:
    cache_key = 'org_custom_fields'
    redis = await get_redis_client()
    if fields_data := await redis.get(cache_key):
        return [PDExtraField(**field) for field in json.loads(fields_data)]
    else:
        pd_fields = (await pipedrive_request('organizationFields'))['data']
        fields = []
        for pd_field in pd_fields:
            if len(pd_field['key']) > 35:
                # Custom fields all have long names
                field = PDExtraField(**pd_field)
                fields.append(field)
        await redis.set(cache_key, json.dumps([f.dict() for f in fields]), ex=300)
        return fields

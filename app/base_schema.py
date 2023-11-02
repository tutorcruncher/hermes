from typing import Any

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from pydantic._internal._model_construction import object_setattr
from tortoise.exceptions import DoesNotExist


def ForeignKeyField(*args, model: Any, fk_field_name: str = 'id', null_if_invalid: bool = False, **kwargs):
    """
    Generates a custom field type for Pydantic that allows us to validate a foreign key by querying the db using the
    a_validate method below, then add the related object to the model as an attribute.

    For example, an Organisation has an owner_id which links to an Admin, so we define

    class Organisation:
        owner_id: fk_field(Admin, 'pd_owner_id', alias='admin')

    Then when we validate the Organisation, we'll query the db to check that an Admin with the `pd_owner_id=owner_id`,
    and if it does, we'll add it to the Organisation as an attribute using `alias` as the field name.
    In the example above, you'll be able to do Organisation.admin to get the owner.
    """
    field_info = Field(*args, **kwargs)
    field_info.json_schema_extra = {
        'is_fk_field': True,
        'model': model,
        'fk_field_name': fk_field_name,
        'alias': kwargs.get('serialization_alias') or field_info.serialization_alias or model.__name__.lower(),
        'null_if_invalid': null_if_invalid,
    }
    return field_info


class HermesBaseModel(BaseModel):
    async def a_validate(self):
        """
        Validates any ForeignKeys on the model by querying the db.
        Annoyingly, we can't do this in Pydantic's built in validation as it doesn't support async validators.
        """
        for field_name, field_info in self.model_fields.items():
            v = getattr(self, field_name)
            extra_schema = field_info.json_schema_extra or {}
            if extra_schema.get('is_fk_field'):
                model = extra_schema['model']
                fk_field_name = extra_schema['fk_field_name']
                if v:
                    try:
                        related_obj = await model.get(**{fk_field_name: v})
                    except DoesNotExist:
                        if extra_schema['null_if_invalid']:
                            object_setattr(self, field_info.serialization_alias, None)
                        else:
                            raise RequestValidationError(
                                [
                                    {
                                        'loc': [field_name],
                                        'msg': f'{model.__name__} with {fk_field_name} {v} does not exist',
                                        'type': 'value_error',
                                    }
                                ]
                            )
                    else:
                        object_setattr(self, field_info.serialization_alias, related_obj)
                else:
                    object_setattr(self, field_info.serialization_alias, None)
            elif hasattr(v, 'a_validate'):
                await v.a_validate()

    model_config = ConfigDict(arbitrary_types_allowed=True)

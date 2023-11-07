from typing import Any

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from pydantic._internal._model_construction import object_setattr
from pydantic.fields import FieldInfo
from tortoise.exceptions import DoesNotExist


def fk_json_schema_extra(
    model: Any, fk_field_name: str = 'id', null_if_invalid: bool = False, custom: bool = False, to_field: str = None
):
    """
    Generates a json schema for a ForeignKeyFieldInfo field.
    """
    return {
        'is_fk_field': True,
        'model': model,
        'fk_field_name': fk_field_name,
        'to_field': to_field or model.__name__.lower(),
        'null_if_invalid': null_if_invalid,
        'custom': custom,
    }


def ForeignKeyFieldInfo(
    *args,
    model: Any,
    fk_field_name: str = 'id',
    null_if_invalid: bool = False,
    custom: bool = False,
    to_field: str = None,
    **kwargs,
) -> FieldInfo:
    """
    Generates a custom field type for Pydantic that allows us to validate a foreign key by querying the db using the
    a_validate method below, then add the related object to the model as an attribute.

    For example, an Organisation has an owner_id which links to an Admin, so we define

    class Organisation:
        owner_id: int = ForeignKeyFieldInfo(model=Admin, fk_field_name='pd_owner_id', alias='admin')

    Then when we validate the Organisation, we'll query the db to check that an Admin with the `pd_owner_id=owner_id`,
    and if it does, we'll add it to the Organisation as an attribute using `alias` as the field name.
    In the example above, you'll be able to do Organisation.admin to get the owner.
    """
    field_info = Field(*args, serialization_alias=to_field, **kwargs)
    field_info.json_schema_extra = fk_json_schema_extra(
        model, fk_field_name=fk_field_name, null_if_invalid=null_if_invalid, custom=custom, to_field=to_field
    )
    return field_info


class HermesBaseModel(BaseModel):
    async def a_validate(self):
        """
        Validates any ForeignKeys on the model by querying the db.
        Annoyingly, we can't do this in Pydantic's built in validation as it doesn't support async validators.
        """
        for field_name, field_info in self.model_fields.items():
            v = getattr(self, field_name, None)
            extra_schema = field_info.json_schema_extra or {}
            if extra_schema.get('is_fk_field'):
                model = extra_schema['model']
                fk_field_name = extra_schema['fk_field_name']
                to_field = extra_schema['to_field']
                if v:
                    try:
                        related_obj = await model.get(**{fk_field_name: v})
                    except DoesNotExist:
                        if extra_schema['null_if_invalid']:
                            object_setattr(self, to_field, None)
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
                        object_setattr(self, to_field, related_obj)
                else:
                    object_setattr(self, to_field, None)
            elif hasattr(v, 'a_validate'):
                await v.a_validate()

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

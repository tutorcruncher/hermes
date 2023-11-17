from typing import Any, TYPE_CHECKING, Type, Optional

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from pydantic._internal._model_construction import object_setattr
from pydantic.fields import FieldInfo
from tortoise.exceptions import DoesNotExist
from tortoise.query_utils import Prefetch

if TYPE_CHECKING:  # noqa
    from app.models import CustomField, Company, Deal, Contact, Meeting


def fk_json_schema_extra(
    model: Any, fk_field_name: str = 'id', null_if_invalid: bool = False, custom: bool = False, to_field: str = None
):
    """
    Generates a json schema for a ForeignKeyField field.
    """
    return {
        'is_fk_field': True,
        'hermes_model': model,
        'fk_field_name': fk_field_name,
        'to_field': to_field or model.__name__.lower(),
        'null_if_invalid': null_if_invalid,
        'custom': custom,
    }


def ForeignKeyField(
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
    a_validate method below, then add the related object to the hermes_model as an attribute.

    For example, an Organisation has an owner_id which links to an Admin, so we define

    class Organisation:
        owner_id: int = ForeignKeyField(hermes_model=Admin, fk_field_name='pd_owner_id', alias='admin')

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
        Validates any ForeignKeys on the hermes_model by querying the db.
        Annoyingly, we can't do this in Pydantic's built in validation as it doesn't support async validators.
        """
        for field_name, field_info in self.model_fields.items():
            v = getattr(self, field_name, None)
            extra_schema = field_info.json_schema_extra or {}
            if extra_schema.get('is_fk_field'):
                model = extra_schema['hermes_model']
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

    @classmethod
    async def get_custom_fields(cls, obj):
        from app.models import CustomField, CustomFieldValue

        model = obj.__class__
        return await CustomField.filter(linked_object_type=model.__name__).prefetch_related(
            Prefetch('values', queryset=CustomFieldValue.filter(**{model.__name__.lower(): obj}))
        )

    async def custom_field_values(self, custom_fields: list['CustomField']) -> dict:
        """
        When updating a Hermes hermes_model from a Pipedrive/TC2 webhook, we need to get the custom field values from
        the Pipedrive/TC2 hermes_model.
        """
        raise NotImplementedError

    @classmethod
    async def get_custom_field_vals(cls, obj) -> dict:
        """
        When creating a Hermes hermes_model from a Pipedrive/TC2 object, gets the custom field values from the
        hermes_model.
        """
        custom_fields = await cls.get_custom_fields(obj)
        cf_data = {}
        for cf in custom_fields:
            if cf.hermes_field_name:
                val = getattr(obj, cf.hermes_field_name, None)
            else:
                val = cf.values[0].value if cf.values else None
            cf_data[cf.machine_name] = val
        return cf_data

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)


async def get_custom_fieldinfo(
    field: 'CustomField',
    model: Type['Company'] | Type['Deal'] | Type['Contact'] | Type['Meeting'],
    **extra_field_kwargs,
) -> FieldInfo:
    """
    Generates the FieldInfo object for custom fields.
    if the field has a hermes_field_name, we'll use that to get the default value from the hermes_model.
    """
    from app.models import CustomField

    field_kwargs = {
        'title': field.name,
        'default': None,
        'required': False,
        'json_schema_extra': {'custom': True},
        **extra_field_kwargs,
    }
    if (
        field.hermes_field_name
        and field.hermes_field_name in model._meta.fields_map
        and (model_default := model._meta.fields_map[field.hermes_field_name].default) is not None
    ):
        field_kwargs['default'] = model_default
    if field.field_type == CustomField.TYPE_INT:
        field_kwargs['annotation'] = Optional[int]
    elif field.field_type == CustomField.TYPE_STR:
        field_kwargs['annotation'] = Optional[str]
    elif field.field_type == CustomField.TYPE_BOOL:
        field_kwargs['annotation'] = Optional[bool]
    elif field.field_type == CustomField.TYPE_FK_FIELD:
        field_kwargs.update(annotation=Optional[int], json_schema_extra=fk_json_schema_extra(model, custom=True))
    return FieldInfo(**field_kwargs)


async def build_custom_field_schema():
    """
    Adds extra fields to the schema for the Pydantic models based on CustomFields in the DB
    """
    from app.pipedrive.tasks import pd_rebuild_schema_with_custom_fields
    from app.tc2.tasks import tc2_rebuild_schema_with_custom_fields

    py_models = list(await pd_rebuild_schema_with_custom_fields()) + list(await tc2_rebuild_schema_with_custom_fields())
    for model in py_models:
        model.model_rebuild(force=True)

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from pydantic.main import object_setattr
from tortoise.exceptions import DoesNotExist


def fk_field(model, fk_field_name='pk', alias=None, null_if_invalid=False):
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

    class ForeignKeyField(int):
        async def get_object(self, k: str, v: str):
            """
            Get the object for the related field. This is used to validate the field.
            """
            try:
                related_obj = await model.get(**{self.fk_field_name: v})
            except DoesNotExist:
                if self.null_if_invalid:
                    return
                else:
                    raise RequestValidationError(
                        [
                            {
                                'loc': [k],
                                'msg': f'{model.__name__} with {self.fk_field_name} {v} does not exist',
                                'type': 'value_error',
                            }
                        ]
                    )
            else:
                return related_obj

    # The attribute name that will be used to store the related object on the model. By default it uses the model name
    setattr(ForeignKeyField, 'alias', alias or model.__name__.lower())

    # The model that the foreign key links to
    setattr(ForeignKeyField, 'model', model)

    # The name of the field on the model that the foreign key links to
    setattr(ForeignKeyField, 'fk_field_name', fk_field_name)

    # Whether or not to set the attribute to None if the foreign key is invalid
    setattr(ForeignKeyField, 'null_if_invalid', null_if_invalid)

    return ForeignKeyField


class HermesBaseModel(BaseModel):
    async def a_validate(self):
        """
        Validates any ForeignKeys on the model by querying the db.
        Annoyingly, we can't do this in Pydantic's built in validation as it doesn't support async validators.
        """
        for field_name, field in self.__fields__.items():
            v = getattr(self, field_name)
            if field.type_.__name__ == 'ForeignKeyField':
                if v:
                    related_obj = await field.type_.get_object(field_name, v)
                    if related_obj:
                        object_setattr(self, field.type_.alias, related_obj)
                    else:
                        object_setattr(self, field.type_.alias, None)
                else:
                    object_setattr(self, field.type_.alias, None)
            elif hasattr(v, 'a_validate'):
                await v.a_validate()

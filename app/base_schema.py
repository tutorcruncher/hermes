from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Extra
from tortoise.exceptions import DoesNotExist


def fk_field(model, fk_field_name='pk', alias=None):
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
        @classmethod
        def alias(cls):
            """
            The attribute name that will be used to store the related object on the model. By default it uses the
            model name in lowercase.
            """
            return alias or model.__name__.lower()

        @classmethod
        def model(cls):
            """
            The model that the foreign key links to.
            """
            return model

        @classmethod
        def fk_field_name(cls):
            """
            The name of the field on the model that the foreign key links to.
            """
            return fk_field_name

    return ForeignKeyField


class HermesBaseModel(BaseModel, extra=Extra.allow):
    async def a_validate(self):
        """
        Validates any ForeignKeys on the model by querying the db.
        Annoyingly, we can't do this in Pydantic's built in validation as it doesn't support async validators.
        """
        for field_name, field in self.__fields__.items():
            v = getattr(self, field_name)
            if field.type_.__name__ == 'ForeignKeyField':
                model = field.type_.model()
                field_name = field.type_.fk_field_name()
                if v:
                    try:
                        related_obj = await model.get(**{field_name: v})
                    except DoesNotExist:
                        raise RequestValidationError(
                            [
                                {
                                    'loc': [field.name],
                                    'msg': f'{model.__name__} with {field_name} {v} does not exist',
                                    'type': 'value_error',
                                }
                            ]
                        )
                    else:
                        setattr(self, field.type_.alias(), related_obj)
                else:
                    setattr(self, field.type_.alias(), None)
            elif hasattr(v, 'a_validate'):
                await v.a_validate()

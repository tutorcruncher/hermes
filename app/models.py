from fastapi_admin.models import AbstractAdmin
from tortoise import fields, models
from tortoise.contrib.pydantic import pydantic_model_creator

from app.utils import settings


def _meeting_min_max_validator(value: str):
    try:
        h, m = value.split(':')
        assert 0 <= int(h) <= 23, 'Hour must be between 0 and 23'
        assert 0 <= int(m) <= 59, 'Minute must be between 0 and 59'
    except (ValueError, AssertionError):
        raise ValueError('Must be a valid time in the format HH:MM')


class Config(models.Model):
    """
    The model that stores the configuration for the app.
    """

    meeting_dur_mins = fields.IntField(default=30, description='The length of a newly created meeting')
    meeting_buffer_mins = fields.IntField(default=15, description='The buffer time before and after a meeting')
    meeting_min_start = fields.CharField(
        max_length=5,
        default='10:00',
        validators=[_meeting_min_max_validator],
        description='The earliest time a meeting can be booked for an admin in their timezone.',
    )
    meeting_max_end = fields.CharField(
        max_length=5,
        default='17:30',
        validators=[_meeting_min_max_validator],
        description='The earliest time a meeting can be booked for an admin in their timezone.',
    )

    payg_pipeline: fields.ForeignKeyRelation['Pipeline'] = fields.ForeignKeyField(
        'models.Pipeline',
        null=True,
        related_name='payg_pipeline',
        description='The pipeline that PAYG clients will be added to',
    )
    startup_pipeline: fields.ForeignKeyRelation['Pipeline'] = fields.ForeignKeyField(
        'models.Pipeline',
        null=True,
        related_name='startup_pipeline',
        description='The pipeline that Startup clients will be added to',
    )
    enterprise_pipeline: fields.ForeignKeyRelation['Pipeline'] = fields.ForeignKeyField(
        'models.Pipeline',
        null=True,
        related_name='enterprise_pipeline',
        description='The pipeline that Enterprise clients will be added to',
    )


class Stage(models.Model):
    id = fields.IntField(primary_key=True)
    pd_stage_id = fields.IntField(unique=True)
    name = fields.CharField(max_length=255)
    # It would be nice to add pipeline as an FK here, but we need dft_entry_stage on the pipeline, and one of
    # Tortoise's limitations is that they don't allow cyclic references (even when the feel is nullable :/)
    # https://github.com/tortoise/tortoise-orm/issues/379

    deals: fields.ReverseRelation['Deal']

    def __str__(self):
        return self.name


class Pipeline(models.Model):
    id = fields.IntField(primary_key=True)
    pd_pipeline_id = fields.IntField(unique=True)
    name = fields.CharField(max_length=255)
    dft_entry_stage = fields.ForeignKeyField('models.Stage', null=True)

    deals: fields.ReverseRelation['Deal']

    def __str__(self):
        return self.name


class Admin(AbstractAdmin):
    id = fields.IntField(primary_key=True)
    tc2_admin_id = fields.IntField(unique=True, null=True)
    pd_owner_id = fields.IntField(null=True)

    first_name = fields.CharField(max_length=255, default='')
    last_name = fields.CharField(max_length=255, default='')

    # This should be the user's actual email address, but it's a pain to overwrite fastapi to use email address instead
    # of username, so we use username and have a property for email.
    username = fields.CharField(max_length=255, description='Use their ACTUAL email address, not META')
    timezone = fields.CharField(max_length=255, default=settings.dft_timezone)

    is_sales_person = fields.BooleanField(default=False)
    is_support_person = fields.BooleanField(default=False)
    is_bdr_person = fields.BooleanField(default=False)

    sells_payg = fields.BooleanField(default=False)
    sells_startup = fields.BooleanField(default=False)
    sells_enterprise = fields.BooleanField(default=False)

    sells_us = fields.BooleanField(default=False)
    sells_gb = fields.BooleanField(default=False)
    sells_au = fields.BooleanField(default=False)
    sells_ca = fields.BooleanField(default=False)
    sells_eu = fields.BooleanField(default=False)
    sells_row = fields.BooleanField(default=False)

    password = fields.CharField(max_length=255, null=True)

    deals: fields.ReverseRelation['Deal']

    @property
    def email(self):
        return self.username

    def __str__(self):
        return self.name

    @property
    def name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    @property
    def call_booker_url(self):
        return f'{settings.callbooker_base_url}/{self.id}/'

    @classmethod
    def pydantic_schema(cls):
        return pydantic_model_creator(
            cls,
            include=(
                'username',
                'id',
                'tc2_admin_id',
                'pd_owner_id',
                'first_name',
                'last_name',
                'timezone',
                'is_sales_person',
                'is_support_person',
                'is_bdr_person',
                'sells_payg',
                'sells_startup',
                'sells_enterprise',
                'sells_us',
                'sells_gb',
                'sells_au',
                'sells_ca',
                'sells_eu',
                'sells_row',
            ),
        )


class HermesModel(models.Model):
    async def process_custom_field_vals(self, old_cf_vals, new_cf_vals) -> tuple[list[str], list[str], list[str]]:
        """
        Process and update custom field values for a model instance. These are not connected to CustomField objects

        This method compares old and new custom field values, identifies which values need to be created, updated, or deleted,
        and performs the necessary database operations.

        Args:
            old_cf_vals (dict): A dictionary of old custom field values.
            new_cf_vals (dict): A dictionary of new custom field values.

        Returns:
            tuple[list[str], list[str], list[str]]: A tuple containing the lists of custom_field_ids for created, updated, and deleted custom field values.
        """
        # Identify new or updated custom field values
        updated_created_vals = {k: v for k, v in new_cf_vals.items() if k not in old_cf_vals and v is not None}
        updated_created_vals |= {k: new_cf_vals[k] for k, v in old_cf_vals.items() if v != new_cf_vals[k]}

        # Identify custom field values to be deleted
        deleted_vals = [k for k, v in old_cf_vals.items() if not v and not new_cf_vals.get(k)]

        created, updated, deleted = [], [], []
        linked_obj_name = self.__class__.__name__.lower()

        for cf_id, cf_val in updated_created_vals.items():
            _, is_created = await CustomFieldValue.update_or_create(
                **{'custom_field_id': cf_id, linked_obj_name: self, 'defaults': {'value': cf_val}}
            )
            if is_created:
                created.append(cf_id)
            else:
                updated.append(cf_id)

        await CustomFieldValue.filter(**{'custom_field_id__in': deleted_vals, linked_obj_name: self}).delete()
        deleted.extend(deleted_vals)

        return created, updated, deleted

    @classmethod
    def pydantic_schema(cls):
        return pydantic_model_creator(cls)


class Company(HermesModel):
    """
    Represents a company.
    In TC this is a mix between a meta Client and an Agency.
    In Pipedrive this is an Organization.
    """

    # These are taken directly from TC2
    STATUS_PENDING_EMAIL_CONF = 'pending_email_conf'
    STATUS_TRIAL = 'trial'
    STATUS_PAYING = 'active'
    STATUS_NOT_PAYING = 'active-not-paying'
    STATUS_SUSPENDED = 'suspended'
    STATUS_TERMINATED = 'terminated'
    STATUS_IN_ARREARS = 'in-arrears'

    PP_PAYG: str = 'payg'
    PP_STARTUP: str = 'startup'
    PP_ENTERPRISE: str = 'enterprise'

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)

    tc2_agency_id = fields.IntField(unique=True, null=True)
    tc2_cligency_id = fields.IntField(unique=True, null=True)
    tc2_status = fields.CharField(max_length=25, default=STATUS_PENDING_EMAIL_CONF, null=True)

    pd_org_id = fields.IntField(unique=True, null=True)

    created = fields.DatetimeField(auto_now_add=True)

    price_plan = fields.CharField(max_length=255, default=PP_PAYG)
    country = fields.CharField(max_length=255, description='Country', null=True)
    website = fields.CharField(max_length=255, null=True)
    paid_invoice_count = fields.IntField(default=0)
    estimated_income = fields.CharField(max_length=255, null=True)
    currency = fields.CharField(max_length=255, null=True)
    has_booked_call = fields.BooleanField(default=False)
    has_signed_up = fields.BooleanField(default=False)
    utm_campaign = fields.CharField(max_length=255, null=True)
    utm_source = fields.CharField(max_length=255, null=True)
    narc = fields.BooleanField(default=False)

    signup_questionnaire = fields.JSONField(null=True)
    pay0_dt = fields.DatetimeField(null=True)
    pay1_dt = fields.DatetimeField(null=True)
    pay3_dt = fields.DatetimeField(null=True)
    gclid = fields.CharField(max_length=255, null=True)
    gclid_expiry_dt = fields.DatetimeField(null=True)
    email_confirmed_dt = fields.DatetimeField(null=True)
    card_saved_dt = fields.DatetimeField(null=True)

    sales_person = fields.ForeignKeyField('models.Admin', related_name='sales')
    support_person = fields.ForeignKeyField('models.Admin', related_name='companies', null=True)
    bdr_person = fields.ForeignKeyField('models.Admin', related_name='leads', null=True)

    contacts: fields.ReverseRelation['Contact']
    deals: fields.ReverseRelation['Deal']
    meetings: fields.ReverseRelation['Meeting']
    custom_field_values: fields.ReverseRelation['CustomFieldValue']

    def __str__(self):
        return self.name

    @property
    def pd_org_url(self):
        if self.pd_org_id:
            return f'{settings.pd_base_url}/organization/{self.pd_org_id}/'
        return None

    @property
    def tc2_cligency_url(self) -> str:
        if self.tc2_cligency_id:
            return f'{settings.tc2_base_url}/clients/{self.tc2_cligency_id}/'
        else:
            return ''


class Contact(HermesModel):
    """
    Represents a contact, an individual who works at a company.
    In TC this is a mix between a meta Client and SR.
    In Pipedrive this is an Person.
    """

    id = fields.IntField(primary_key=True)
    tc2_sr_id = fields.IntField(unique=True, null=True)
    pd_person_id = fields.IntField(unique=True, null=True)
    created = fields.DatetimeField(auto_now_add=True)

    first_name = fields.CharField(max_length=255, null=True)
    last_name = fields.CharField(max_length=255, null=True)
    email = fields.CharField(max_length=255, null=True)
    phone = fields.CharField(max_length=255, null=True)
    country = fields.CharField(max_length=255, null=True)

    company = fields.ForeignKeyField('models.Company', related_name='contacts')

    custom_field_values: fields.ReverseRelation['CustomFieldValue']

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.email})'

    @property
    def name(self):
        if self.first_name:
            return f'{self.first_name} {self.last_name}'
        return self.last_name


class Deal(HermesModel):
    STATUS_OPEN = 'open'
    STATUS_WON = 'won'
    STATUS_LOST = 'lost'
    STATUS_DELETED = 'deleted'

    id = fields.IntField(primary_key=True)
    pd_deal_id = fields.IntField(unique=True, null=True)

    name = fields.CharField(max_length=255, null=True)

    status = fields.CharField(max_length=255, default=STATUS_OPEN)

    admin = fields.ForeignKeyField('models.Admin', related_name='deals')
    pipeline = fields.ForeignKeyField('models.Pipeline', related_name='deals')

    stage = fields.ForeignKeyField('models.Stage', related_name='deals')
    company = fields.ForeignKeyField('models.Company', related_name='deals')
    contact = fields.ForeignKeyField('models.Contact', related_name='deals', null=True)

    custom_field_values: fields.ReverseRelation['CustomFieldValue']

    def __str__(self):
        return self.name


class Meeting(HermesModel):
    STATUS_PLANNED = 'PLANNED'
    STATUS_CANCELED = 'CANCELED'
    STATUS_NO_SHOW = 'NO_SHOW'
    STATUS_COMPLETED = 'COMPLETED'

    TYPE_SALES = 'sales'
    TYPE_SUPPORT = 'support'

    id = fields.IntField(primary_key=True)

    created = fields.DatetimeField(auto_now_add=True)

    start_time = fields.DatetimeField(null=True)
    end_time = fields.DatetimeField(null=True)
    status = fields.CharField(max_length=255, default=STATUS_PLANNED)
    meeting_type = fields.CharField(max_length=255)

    admin = fields.ForeignKeyField('models.Admin', related_name='meetings')
    contact = fields.ForeignKeyField('models.Contact', related_name='meetings')
    deal = fields.ForeignKeyField('models.Deal', related_name='meetings', null=True, on_delete=fields.SET_NULL)

    custom_field_values: fields.ReverseRelation['CustomFieldValue']

    @property
    def name(self):
        if self.meeting_type == Meeting.TYPE_SALES:
            return f'TutorCruncher demo with {self.admin.name}'
        else:
            assert self.meeting_type == Meeting.TYPE_SUPPORT
            return f'TutorCruncher support meeting with {self.admin.name}'


def _slugify(name: str) -> str:
    return name.lower().replace(' ', '_')


class CustomField(models.Model):
    """
    Used to store the custom fields that we have in Pipedrive/TC. When the app is started, we run
    build_custom_field_schema() to add the custom fields to the relevant models.

    There are different ways CustomFields are linked to the Hermes Model they relate to, best explained with examples.

    Example 1: We want to record 'Source' to track where a signup has come from (Google etc).
    This field doesn't exist on the Company model. We create a AttributeDefinition in TC2 with the machine_name `source`
    We also create a custom field in Pipedrive; the ID of that field is 123_source_456. Lastly, we create a CustomField
    with the attributes:

        name='Source',
        machine_name='source',  # Although this is created automatically on save)
        field_type=CustomField.TYPE_STR,
        hermes_field_name=null,  # This is null because the field doesn't exist on the model
        tc2_machine_name=source,
        pd_field_id=123_source_456,
        linked_object_type=Company.__name__.

    When the app starts, `build_custom_field_schema` will add a field to the Organisation model. The field has the name
    `source` and has an alias for `123_source_456` (aliases in Pydantic mean we can refer to them by that name
    instead. Check the docs for details.) When a webhook comes in from PD we can do validation on the field value.
    This is especially useful when combined with the ForeignKeyField. See ForeignKeyField for details.

    When the webhook from PD comes through, the field `source` will be set on the model as it comes from PD with the
    key `123_source_456` and we've used an alias to tell Pydantic to fill from that field. If the webhook was coming
    from TC2 then we'd check for an `extra_attr` with the `machine_name` equal to the CustomField's `tc2_machine_name`.

    When the Object, in this case a Company object, is saved to the DB, we create or update a CustomFieldValue linked
    to the CustomField object with the attributes:

        custom_field=the_custom_field_created_above,
        company=the_company_object,
        value="Google"

    Example 2: We want to record the estimated income of a Company. This field exists on the Company model as it is one
    of the fields available from the Callbooker.
    First, we create a custom field in Pipedrive for estimated_income; the ID of that field is 123_income_456. We also
    create the AttDef in TC2. We then create a CustomField with the attributes:

        name='Estimated income',
        machine_name='estimated_income',  # Although this is created automatically on save)
        field_type=CustomField.TYPE_STR,
        hermes_field_name=estimated_income,  # We use the name of the field on the model
        tc2_machine_name=estimated_income,
        pd_field_id=123_income_456,
        linked_object_type=Company.__name__.

    The logic is similar to above, except that when the object is saved to the DB we look at the CustomField's
    `hermes_field_name` and fill the value to that field. No CustomFieldValue is created.
    """

    TYPE_INT = 'int'
    TYPE_STR = 'str'
    TYPE_BOOL = 'bool'
    TYPE_FK_FIELD = 'fk_field'
    TYPE_DATE = 'date'
    TYPE_CHOICES = (
        (TYPE_INT, TYPE_INT),
        (TYPE_STR, TYPE_STR),
        (TYPE_BOOL, TYPE_BOOL),
        (TYPE_FK_FIELD, TYPE_FK_FIELD),
        (TYPE_DATE, TYPE_DATE),
    )

    id = fields.IntField(primary_key=True)

    name = fields.CharField(max_length=255)
    machine_name = fields.CharField(max_length=255, null=True)
    field_type = fields.CharField(
        max_length=255,
        choices=(TYPE_INT, TYPE_STR, TYPE_BOOL, TYPE_FK_FIELD, TYPE_DATE),
        description='The type of field.',
    )

    hermes_field_name = fields.CharField(
        max_length=255,
        null=True,
        description='If this is connected to data from the Hermes model, this is the field name. Eg: `website`',
    )
    tc2_machine_name = fields.CharField(
        max_length=255, null=True, description='The machine name of the Custom Field in TC2, if not in the normal data.'
    )
    pd_field_id = fields.CharField(max_length=255, null=True, description='The ID of the Custom Field in Pipedrive')
    linked_object_type = fields.CharField(
        max_length=255,
        description='The name of the model this is linked to, ("Company", "Contact", "Deal", "Meeting")',
    )

    values: fields.ReverseRelation['CustomFieldValue']

    async def save(self, *args, **kwargs) -> None:
        if not self.machine_name:
            self.machine_name = _slugify(self.name)
        return await super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def __repr__(self):
        return str(self)

    class Meta:
        unique_together = ('machine_name', 'linked_object_type')


class CustomFieldValue(models.Model):
    id = fields.IntField(primary_key=True)

    custom_field = fields.ForeignKeyField('models.CustomField', related_name='values')

    company = fields.ForeignKeyField(
        'models.Company', related_name='custom_field_values', null=True, on_delete=fields.CASCADE
    )
    contact = fields.ForeignKeyField(
        'models.Contact', related_name='custom_field_values', null=True, on_delete=fields.CASCADE
    )
    deal = fields.ForeignKeyField(
        'models.Deal', related_name='custom_field_values', null=True, on_delete=fields.CASCADE
    )
    meeting = fields.ForeignKeyField(
        'models.Meeting', related_name='custom_field_values', null=True, on_delete=fields.CASCADE
    )

    value = fields.CharField(max_length=10000, null=True)

    def validate(self):
        if not (self.company or self.contact or self.deal or self.meeting):
            raise ValueError('Must have a company, contact, deal or meeting')

    def __str__(self):
        return f'{self.custom_field}: {self.value}'

    def __repr__(self):
        return str(self)

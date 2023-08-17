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

    payg_pipeline = fields.ForeignKeyField(
        'models.Pipeline',
        null=True,
        related_name='payg_pipeline',
        description='The pipeline that PAYG clients will be added to',
    )
    startup_pipeline = fields.ForeignKeyField(
        'models.Pipeline',
        null=True,
        related_name='startup_pipeline',
        description='The pipeline that Startup clients will be added to',
    )
    enterprise_pipeline = fields.ForeignKeyField(
        'models.Pipeline',
        null=True,
        related_name='enterprise_pipeline',
        description='The pipeline that Enterprise clients will be added to',
    )


class Stage(models.Model):
    id = fields.IntField(pk=True)
    pd_stage_id = fields.IntField(unique=True)
    name = fields.CharField(max_length=255)
    # It would be nice to add pipeline as an FK here, but we need dft_entry_stage on the pipeline, and one of
    # Tortoise's limitations is that they don't allow cyclic references (even when the feel is nullable :/)
    # https://github.com/tortoise/tortoise-orm/issues/379

    deals: fields.ReverseRelation['Deal']


class Pipeline(models.Model):
    id = fields.IntField(pk=True)
    pd_pipeline_id = fields.IntField(unique=True)
    name = fields.CharField(max_length=255)
    dft_entry_stage = fields.ForeignKeyField('models.Stage', null=True)

    deals: fields.ReverseRelation['Deal']


class Admin(AbstractAdmin):
    id = fields.IntField(pk=True)
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
            ),
        )


class Company(models.Model):
    """
    Represents a company.
    In TC this is a mix between a meta Client and an Agency.
    In Pipedrive this is an Organization.
    """

    STATUS_PENDING_EMAIL_CONF = 'pending_email_conf'
    STATUS_TRIAL = 'trial'
    STATUS_PAYING = 'active'
    STATUS_NOT_PAYING = 'active-not-paying'
    STATUS_SUSPENDED = 'suspended'
    STATUS_TERMINATED = 'terminated'
    STATUS_IN_ARREARS = 'in-arrears'

    PP_PAYG = 'payg'
    PP_STARTUP = 'startup'
    PP_ENTERPRISE = 'enterprise'

    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255)

    tc2_agency_id = fields.IntField(unique=True, null=True)
    tc2_cligency_id = fields.IntField(unique=True, null=True)
    tc2_status = fields.CharField(max_length=25, default=STATUS_PENDING_EMAIL_CONF)

    pd_org_id = fields.IntField(unique=True, null=True)

    created = fields.DatetimeField(auto_now_add=True)

    price_plan = fields.CharField(max_length=255, default=PP_PAYG)
    country = fields.CharField(max_length=255, description='Country code, e.g. GB', null=True)
    website = fields.CharField(max_length=255, null=True)
    paid_invoice_count = fields.IntField(default=0)
    estimated_income = fields.CharField(max_length=255, null=True)
    currency = fields.CharField(max_length=255, null=True)
    has_booked_call = fields.BooleanField(default=False)
    has_signed_up = fields.BooleanField(default=False)

    sales_person = fields.ForeignKeyField('models.Admin', related_name='sales')
    support_person = fields.ForeignKeyField('models.Admin', related_name='companies', null=True)
    bdr_person = fields.ForeignKeyField('models.Admin', related_name='leads', null=True)

    contacts: fields.ReverseRelation['Contact']
    deals: fields.ReverseRelation['Deal']
    meetings: fields.ReverseRelation['Meeting']

    def __str__(self):
        return self.name

    @property
    def pd_org_url(self):
        return f'{settings.pd_base_url}/organizations/{self.pd_org_id}/'

    @property
    def tc2_cligency_url(self) -> str:
        if self.tc2_cligency_id:
            return f'{settings.tc2_base_url}/clients/{self.tc2_cligency_id}/'
        else:
            return ''


class Contact(models.Model):
    """
    Represents a contact, an individual who works at a company.
    In TC this is a mix between a meta Client and SR.
    In Pipedrive this is an Person.
    """

    id = fields.IntField(pk=True)
    tc2_sr_id = fields.IntField(unique=True, null=True)
    pd_person_id = fields.IntField(unique=True, null=True)
    created = fields.DatetimeField(auto_now_add=True)

    first_name = fields.CharField(max_length=255, null=True)
    last_name = fields.CharField(max_length=255, null=True)
    email = fields.CharField(max_length=255, null=True)
    phone = fields.CharField(max_length=255, null=True)
    country = fields.CharField(max_length=255, null=True)

    company = fields.ForeignKeyField('models.Company', related_name='contacts')

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.email})'

    @property
    def name(self):
        if self.first_name:
            return f'{self.first_name} {self.last_name}'
        return self.last_name


class Deal(models.Model):
    STATUS_OPEN = 'open'
    STATUS_WON = 'won'
    STATUS_LOST = 'lost'
    STATUS_DELETED = 'deleted'

    id = fields.IntField(pk=True)
    pd_deal_id = fields.IntField(unique=True, null=True)

    name = fields.CharField(max_length=255, null=True)

    status = fields.CharField(max_length=255, default=STATUS_OPEN)

    admin = fields.ForeignKeyField('models.Admin', related_name='deals')
    pipeline = fields.ForeignKeyField('models.Pipeline', related_name='deals')

    # Is null until we get the webhook from Pipedrive
    stage = fields.ForeignKeyField('models.Stage', related_name='deals', null=True)
    company = fields.ForeignKeyField('models.Company', related_name='deals')
    contact = fields.ForeignKeyField('models.Contact', related_name='deals', null=True)

    def __str__(self):
        return self.name


class Meeting(models.Model):
    STATUS_PLANNED = 'PLANNED'
    STATUS_CANCELED = 'CANCELED'
    STATUS_NO_SHOW = 'NO_SHOW'
    STATUS_COMPLETED = 'COMPLETED'

    TYPE_SALES = 'sales'
    TYPE_SUPPORT = 'support'

    id = fields.IntField(pk=True)

    created = fields.DatetimeField(auto_now_add=True)

    start_time = fields.DatetimeField(null=True)
    end_time = fields.DatetimeField(null=True)
    status = fields.CharField(max_length=255, default=STATUS_PLANNED)
    meeting_type = fields.CharField(max_length=255)

    admin = fields.ForeignKeyField('models.Admin', related_name='meetings')
    contact = fields.ForeignKeyField('models.Contact', related_name='meetings')
    deal = fields.ForeignKeyField('models.Deal', related_name='meetings', null=True, on_delete=fields.SET_NULL)

    @property
    def name(self):
        if self.meeting_type == Meeting.TYPE_SALES:
            return f'Introductory call with {self.admin.name}'
        else:
            assert self.meeting_type == Meeting.TYPE_SUPPORT
            return f'Support call with {self.admin.name}'

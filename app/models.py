from tortoise import fields, models
from tortoise.contrib.pydantic import pydantic_model_creator

from app.settings import Settings

settings = Settings()


class BaseModel(models.Model):
    @classmethod
    def py_schema(cls):
        return pydantic_model_creator(cls, name=cls.__name__)

    class Meta:
        abstract = True


class Admins(BaseModel):
    id = fields.IntField(pk=True)
    tc_admin_id = fields.IntField(unique=True)

    first_name = fields.CharField(max_length=255)
    last_name = fields.CharField(max_length=255)
    email = fields.CharField(max_length=255)

    is_sales_person = fields.BooleanField(default=False)
    is_client_manager = fields.BooleanField(default=False)
    is_bdr_person = fields.BooleanField(default=False)

    password = fields.CharField(max_length=255, default='')

    def __str__(self):
        return f'{self.first_name} {self.last_name}'.strip()


class Companies(BaseModel):
    """
    Represents a potential/current company using TutorCruncher.
    """

    STATUS_PENDING_EMAIL_CONF = 'pending_email_conf'
    STATUS_TRIAL = 'trial'
    STATUS_PAYING = 'active'
    STATUS_NOT_PAYING = 'active-not-paying'
    STATUS_SUSPENDED = 'suspended'
    STATUS_TERMINATED = 'terminated'
    STATUS_IN_ARREARS = 'in-arrears'

    id = fields.IntField(pk=True)
    tc_agency_id = fields.IntField(unique=True, null=True)
    tc_cligency_id = fields.IntField(unique=True, null=True)
    created = fields.DatetimeField(auto_now_add=True)
    status = fields.CharField(max_length=25, null=True)

    name = fields.CharField(max_length=255)
    website = fields.CharField(max_length=255, null=True)
    country = fields.CharField(max_length=255, null=True)

    client_manager: fields.ForeignKeyRelation[Admins] = fields.ForeignKeyField(
        'models.Admins', related_name='companies', null=True
    )
    sales_person: fields.ForeignKeyRelation[Admins] = fields.ForeignKeyField(
        'models.Admins', related_name='sales', null=True
    )
    bdr_person: fields.ForeignKeyRelation[Admins] = fields.ForeignKeyField(
        'models.Admins', related_name='leads', null=True
    )

    paid_invoice_count = fields.IntField(default=0)

    estimated_income = fields.CharField(max_length=255, null=True)
    currency = fields.CharField(max_length=255, null=True)
    form_json = fields.JSONField(null=True)

    contacts: fields.ReverseRelation['Contacts']
    deals: fields.ReverseRelation['Deals']
    meetings: fields.ReverseRelation['Meetings']

    def __str__(self):
        return self.name

    @property
    def tc_cligency_url(self):
        return f'{settings.TC_BASE_URL}/clients/{self.tc_cligency_id}/'


class Contacts(BaseModel):
    id = fields.IntField(pk=True)
    tc_sr_id = fields.IntField(unique=True, null=True)

    first_name = fields.CharField(max_length=255, null=True)
    last_name = fields.CharField(max_length=255, null=True)
    email = fields.CharField(max_length=255, null=True)
    phone = fields.CharField(max_length=255, null=True)
    country = fields.CharField(max_length=255, null=True)

    company: fields.ForeignKeyRelation[Companies] = fields.ForeignKeyField('models.Companies', related_name='contacts')

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.email})'

    @property
    def name(self):
        if self.first_name:
            return f'{self.first_name} {self.last_name}'
        return self.last_name


class Deals(BaseModel):
    id = fields.IntField(pk=True)
    hubspot_id = fields.CharField(max_length=255, unique=True)
    tc_sr_id = fields.IntField(unique=True)

    name = fields.CharField(max_length=255, null=True)
    amount = fields.FloatField(null=True)
    close_date = fields.DatetimeField(null=True)
    stage = fields.CharField(max_length=255, null=True)

    contact: fields.ForeignKeyRelation[Contacts] = fields.ForeignKeyField(
        'models.Contacts', related_name='contact_deals'
    )
    company: fields.ForeignKeyRelation[Contacts] = fields.ForeignKeyField(
        'models.Contacts', related_name='company_deals'
    )

    def __str__(self):
        return f'{self.name} ({self.amount})'


class Meetings(BaseModel):
    STATUS_PLANNED = 'PLANNED'
    STATUS_CANCELED = 'CANCELED'
    STATUS_NO_SHOW = 'NO_SHOW'
    STATUS_COMPLETED = 'COMPLETED'

    MEETING_TYPE_SALES = 'SALES'
    MEETING_TYPE_SUPPORT = 'SUPPORT'

    id = fields.IntField(pk=True)

    created = fields.DatetimeField(auto_now_add=True)

    name = fields.CharField(max_length=255, null=True)
    start_time = fields.DatetimeField(null=True)
    status = fields.CharField(max_length=255, default=STATUS_PLANNED)
    meeting_type = fields.CharField(max_length=255)

    admin: fields.ForeignKeyRelation[Admins] = fields.ForeignKeyField('models.Admins', related_name='meetings')
    contact: fields.ForeignKeyRelation[Contacts] = fields.ForeignKeyField('models.Contacts', related_name='meetings')

    def __str__(self):
        return f'{self.name} ({self.start_time})'

from tortoise import fields, models

from app.settings import Settings

settings = Settings()


class Admins(models.Model):
    id = fields.IntField(pk=True)
    tc_admin_id = fields.IntField(unique=True)
    pd_owner_id = fields.IntField(null=True)

    first_name = fields.CharField(max_length=255)
    last_name = fields.CharField(max_length=255)
    email = fields.CharField(max_length=255)
    timezone = fields.CharField(max_length=255, default=settings.dft_timezone)

    is_sales_person = fields.BooleanField(default=False)
    is_client_manager = fields.BooleanField(default=False)
    is_bdr_person = fields.BooleanField(default=False)

    password = fields.CharField(max_length=255, default='')

    def __str__(self):
        return self.name

    @property
    def name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    @property
    def call_booker_url(self):
        return f'{settings.tc_call_booker_url}/{self.first_name.lower()}'


class Companies(models.Model):
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

    id = fields.IntField(pk=True)
    tc_agency_id = fields.IntField(unique=True, null=True)
    tc_cligency_id = fields.IntField(unique=True, null=True)

    pd_org_id = fields.IntField(unique=True, null=True)

    created = fields.DatetimeField(auto_now_add=True)
    status = fields.CharField(max_length=25, default=STATUS_PENDING_EMAIL_CONF)

    name = fields.CharField(max_length=255)
    price_plan = fields.CharField(max_length=255, null=True)
    country = fields.CharField(max_length=255, description='Country code, e.g. GB')
    website = fields.CharField(max_length=255, null=True)

    client_manager = fields.ForeignKeyField('models.Admins', related_name='companies', null=True)
    sales_person = fields.ForeignKeyField('models.Admins', related_name='sales', null=True)
    bdr_person = fields.ForeignKeyField('models.Admins', related_name='leads', null=True)

    paid_invoice_count = fields.IntField(default=0)
    estimated_income = fields.CharField(max_length=255, null=True)
    currency = fields.CharField(max_length=255, null=True)

    has_booked_call = fields.BooleanField(default=False)
    has_signed_up = property(lambda self: bool(self.tc_cligency_id))

    contacts: fields.ReverseRelation['Contacts']
    deals: fields.ReverseRelation['Deals']
    meetings: fields.ReverseRelation['Meetings']

    def __str__(self):
        return self.name

    @property
    def tc_cligency_url(self) -> str:
        if self.tc_cligency_id:
            return f'{settings.tc2_base_url}/clients/{self.tc_cligency_id}/'
        else:
            return ''


class Contacts(models.Model):
    """
    Represents a contact, an individual who works at a company.
    In TC this is a mix between a meta Client and SR.
    In Pipedrive this is an Person.
    """

    id = fields.IntField(pk=True)
    tc_sr_id = fields.IntField(unique=True, null=True)
    pd_person_id = fields.IntField(unique=True, null=True)

    first_name = fields.CharField(max_length=255, null=True)
    last_name = fields.CharField(max_length=255, null=True)
    email = fields.CharField(max_length=255, null=True)
    phone = fields.CharField(max_length=255, null=True)
    country = fields.CharField(max_length=255, null=True)

    company = fields.ForeignKeyField('models.Companies', related_name='contacts')

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.email})'

    @property
    def name(self):
        if self.first_name:
            return f'{self.first_name} {self.last_name}'
        return self.last_name


class Deals(models.Model):
    id = fields.IntField(pk=True)
    hubspot_id = fields.CharField(max_length=255, unique=True)
    tc_sr_id = fields.IntField(unique=True)

    name = fields.CharField(max_length=255, null=True)
    amount = fields.FloatField(null=True)
    close_date = fields.DatetimeField(null=True)
    stage = fields.CharField(max_length=255, null=True)

    contact = fields.ForeignKeyField('models.Contacts', related_name='contact_deals')
    company = fields.ForeignKeyField('models.Contacts', related_name='company_deals')

    def __str__(self):
        return f'{self.name} ({self.amount})'


class Deals(models.Model):
    id = fields.IntField(pk=True)
    company = fields.ForeignKeyField('models.Companies', related_name='deals')


class Meetings(models.Model):
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

    admin = fields.ForeignKeyField('models.Admins', related_name='meetings')
    contact = fields.ForeignKeyField('models.Contacts', related_name='meetings')

    @property
    def name(self):
        admin = await self.admin
        if self.meeting_type == Meetings.TYPE_SALES:
            return f'Introduction call with {admin.name}'
        else:
            assert self.meeting_type == Meetings.TYPE_SUPPORT
            return f'Support call with {admin.name}'

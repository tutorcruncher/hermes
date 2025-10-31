from datetime import datetime, timezone
from typing import ClassVar, List, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.core.config import settings


class Admin(SQLModel, table=True):
    """
    Admin user model representing sales, support, and BDR personnel.
    In TC2 this is an Admin.
    In Pipedrive this maps to a User via pd_owner_id.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    tc2_admin_id: Optional[int] = Field(default=None, unique=True, index=True)
    pd_owner_id: Optional[int] = Field(default=None, index=True)

    first_name: str = Field(default='')
    last_name: str = Field(default='')
    username: str = Field(max_length=255)
    timezone: str = Field(default='Europe/London')

    # Role flags
    is_sales_person: bool = Field(default=False)
    is_support_person: bool = Field(default=False)
    is_bdr_person: bool = Field(default=False)

    # Product flags
    sells_payg: bool = Field(default=False)
    sells_startup: bool = Field(default=False)
    sells_enterprise: bool = Field(default=False)

    # Territory flags
    sells_us: bool = Field(default=False)
    sells_gb: bool = Field(default=False)
    sells_au: bool = Field(default=False)
    sells_ca: bool = Field(default=False)
    sells_eu: bool = Field(default=False)
    sells_row: bool = Field(default=False)

    # Relationships
    sales_companies: List['Company'] = Relationship(
        back_populates='sales_person', sa_relationship_kwargs={'foreign_keys': '[Company.sales_person_id]'}
    )
    support_companies: List['Company'] = Relationship(
        back_populates='support_person', sa_relationship_kwargs={'foreign_keys': '[Company.support_person_id]'}
    )
    bdr_companies: List['Company'] = Relationship(
        back_populates='bdr_person', sa_relationship_kwargs={'foreign_keys': '[Company.bdr_person_id]'}
    )
    deals: List['Deal'] = Relationship(back_populates='admin')
    meetings: List['Meeting'] = Relationship(back_populates='admin')

    @property
    def name(self) -> str:
        return f'{self.first_name} {self.last_name}'.strip()

    @property
    def email(self):
        return self.username

    @property
    def call_booker_url(self):
        return f'{settings.callbooker_base_url}/{self.id}/'

    def __str__(self):
        return self.name


class Pipeline(SQLModel, table=True):
    """Pipedrive Pipeline"""

    id: Optional[int] = Field(default=None, primary_key=True)
    pd_pipeline_id: int = Field(unique=True, index=True)
    name: str = Field(max_length=255)
    dft_entry_stage_id: Optional[int] = Field(default=None, foreign_key='stage.id')

    deals: List['Deal'] = Relationship(back_populates='pipeline')
    dft_entry_stage: 'Stage' = Relationship(
        sa_relationship_kwargs={'foreign_keys': '[Pipeline.dft_entry_stage_id]', 'lazy': 'select'}
    )

    def __str__(self):
        return self.name


class Stage(SQLModel, table=True):
    """Pipedrive Stage"""

    id: Optional[int] = Field(default=None, primary_key=True)
    pd_stage_id: int = Field(unique=True, index=True)
    name: str = Field(max_length=255)

    deals: List['Deal'] = Relationship(back_populates='stage')

    def __str__(self):
        return self.name


class Config(SQLModel, table=True):
    """
    Configuration model for meeting settings and pipeline references.
    Only one Config record should exist.
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    meeting_dur_mins: int = Field(default=30)
    meeting_buffer_mins: int = Field(default=15)
    meeting_min_start: str = Field(default='10:00', max_length=5)
    meeting_max_end: str = Field(default='17:30', max_length=5)

    payg_pipeline_id: int = Field(foreign_key='pipeline.id')
    startup_pipeline_id: int = Field(foreign_key='pipeline.id')
    enterprise_pipeline_id: int = Field(foreign_key='pipeline.id')

    payg_pipeline: Pipeline = Relationship(
        sa_relationship_kwargs={'foreign_keys': '[Config.payg_pipeline_id]', 'lazy': 'select'}
    )
    startup_pipeline: Pipeline = Relationship(
        sa_relationship_kwargs={'foreign_keys': '[Config.startup_pipeline_id]', 'lazy': 'select'}
    )
    enterprise_pipeline: Pipeline = Relationship(
        sa_relationship_kwargs={'foreign_keys': '[Config.enterprise_pipeline_id]', 'lazy': 'select'}
    )


class Company(SQLModel, table=True):
    """
    Represents a company.
    In TC2 this is a mix between a meta Client and an Agency.
    In Pipedrive this is an Organization.
    """

    # Company status constants (from TC2)
    STATUS_PENDING_EMAIL_CONF: ClassVar[str] = 'pending_email_conf'
    STATUS_TRIAL: ClassVar[str] = 'trial'
    STATUS_PAYING: ClassVar[str] = 'active'
    STATUS_NOT_PAYING: ClassVar[str] = 'active-not-paying'
    STATUS_SUSPENDED: ClassVar[str] = 'suspended'
    STATUS_TERMINATED: ClassVar[str] = 'terminated'
    STATUS_IN_ARREARS: ClassVar[str] = 'in-arrears'

    # Price plan constants
    PP_PAYG: ClassVar[str] = 'payg'
    PP_STARTUP: ClassVar[str] = 'startup'
    PP_ENTERPRISE: ClassVar[str] = 'enterprise'

    # Core fields
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)

    # System IDs
    tc2_agency_id: Optional[int] = Field(default=None, unique=True, index=True)
    tc2_cligency_id: Optional[int] = Field(default=None, unique=True, index=True)
    pd_org_id: Optional[int] = Field(default=None, unique=True, index=True)

    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Business fields
    price_plan: str = Field(default=PP_PAYG, max_length=255)
    country: Optional[str] = Field(default=None, max_length=255)
    website: Optional[str] = Field(default=None, max_length=255)
    currency: Optional[str] = Field(default=None, max_length=255)
    estimated_income: Optional[str] = Field(default=None, max_length=255)

    # Marketing fields
    utm_campaign: Optional[str] = Field(default=None, max_length=255)
    utm_source: Optional[str] = Field(default=None, max_length=255)
    gclid: Optional[str] = Field(default=None, max_length=255)
    signup_questionnaire: Optional[str] = Field(default=None)

    # Flags
    has_booked_call: bool = Field(default=False)
    has_signed_up: bool = Field(default=False)
    narc: bool = Field(default=False)

    # Fields synced to/from Pipedrive
    paid_invoice_count: Optional[int] = Field(default=0)
    tc2_status: Optional[str] = Field(default=STATUS_PENDING_EMAIL_CONF, max_length=25)

    # Date fields
    pay0_dt: Optional[datetime] = Field(default=None)
    pay1_dt: Optional[datetime] = Field(default=None)
    pay3_dt: Optional[datetime] = Field(default=None)
    gclid_expiry_dt: Optional[datetime] = Field(default=None)
    email_confirmed_dt: Optional[datetime] = Field(default=None)
    card_saved_dt: Optional[datetime] = Field(default=None)

    # Foreign keys
    sales_person_id: int = Field(foreign_key='admin.id')
    support_person_id: Optional[int] = Field(default=None, foreign_key='admin.id')
    bdr_person_id: Optional[int] = Field(default=None, foreign_key='admin.id')

    # Relationships
    sales_person: Admin = Relationship(
        back_populates='sales_companies', sa_relationship_kwargs={'foreign_keys': '[Company.sales_person_id]'}
    )
    support_person: Optional[Admin] = Relationship(
        back_populates='support_companies', sa_relationship_kwargs={'foreign_keys': '[Company.support_person_id]'}
    )
    bdr_person: Optional[Admin] = Relationship(
        back_populates='bdr_companies', sa_relationship_kwargs={'foreign_keys': '[Company.bdr_person_id]'}
    )
    contacts: List['Contact'] = Relationship(back_populates='company')
    deals: List['Deal'] = Relationship(back_populates='company')
    meetings: List['Meeting'] = Relationship(back_populates='company')

    @property
    def pd_org_url(self):
        if self.pd_org_id:
            return f'{settings.pd_base_url}/organization/{self.pd_org_id}/'
        return None

    @property
    def tc2_cligency_url(self) -> str:
        if self.tc2_cligency_id:
            return f'{settings.tc2_base_url}/clients/{self.tc2_cligency_id}/'
        return ''

    def __str__(self):
        return self.name


class Contact(SQLModel, table=True):
    """
    Represents a contact, an individual who works at a company.
    In TC2 this is a mix between a meta Client and SR.
    In Pipedrive this is a Person.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    tc2_sr_id: Optional[int] = Field(default=None, unique=True, index=True)
    pd_person_id: Optional[int] = Field(default=None, unique=True, index=True)
    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    first_name: Optional[str] = Field(default=None, max_length=255)
    last_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=255)
    country: Optional[str] = Field(default=None, max_length=255)

    # Foreign key
    company_id: int = Field(foreign_key='company.id')

    # Relationships
    company: Company = Relationship(back_populates='contacts')
    deals: List['Deal'] = Relationship(back_populates='contact')
    meetings: List['Meeting'] = Relationship(back_populates='contact')

    @property
    def name(self):
        if self.first_name:
            return f'{self.first_name} {self.last_name}'
        return self.last_name

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.email})'


class Deal(SQLModel, table=True):
    """Pipedrive Deal"""

    STATUS_OPEN: ClassVar[str] = 'open'
    STATUS_WON: ClassVar[str] = 'won'
    STATUS_LOST: ClassVar[str] = 'lost'
    STATUS_DELETED: ClassVar[str] = 'deleted'

    id: Optional[int] = Field(default=None, primary_key=True)
    pd_deal_id: Optional[int] = Field(default=None, unique=True, index=True)

    name: Optional[str] = Field(default=None, max_length=255)
    status: str = Field(default=STATUS_OPEN, max_length=255)

    # Foreign keys
    admin_id: int = Field(foreign_key='admin.id')
    pipeline_id: int = Field(foreign_key='pipeline.id')
    stage_id: int = Field(foreign_key='stage.id')
    company_id: int = Field(foreign_key='company.id')
    contact_id: Optional[int] = Field(default=None, foreign_key='contact.id')

    # All company extra fields (synced to/from Pipedrive)
    support_person_id: Optional[int] = Field(default=None)
    bdr_person_id: Optional[int] = Field(default=None)
    paid_invoice_count: Optional[int] = Field(default=0)
    tc2_status: Optional[str] = Field(default=None)
    tc2_cligency_url: Optional[str] = Field(default=None, max_length=255)
    website: Optional[str] = Field(default=None)
    price_plan: Optional[str] = Field(default=None)
    estimated_income: Optional[str] = Field(default=None)
    signup_questionnaire: Optional[str] = Field(default=None)
    utm_campaign: Optional[str] = Field(default=None)
    utm_source: Optional[str] = Field(default=None)

    # Relationships
    admin: Admin = Relationship(back_populates='deals')
    pipeline: Pipeline = Relationship(back_populates='deals')
    stage: Stage = Relationship(back_populates='deals')
    company: Company = Relationship(back_populates='deals')
    contact: Optional[Contact] = Relationship(back_populates='deals')
    meetings: List['Meeting'] = Relationship(back_populates='deal')

    def __str__(self):
        return self.name or f'Deal {self.id}'


class Meeting(SQLModel, table=True):
    """Meeting/Activity model"""

    STATUS_PLANNED: ClassVar[str] = 'PLANNED'
    STATUS_CANCELED: ClassVar[str] = 'CANCELED'
    STATUS_NO_SHOW: ClassVar[str] = 'NO_SHOW'
    STATUS_COMPLETED: ClassVar[str] = 'COMPLETED'

    TYPE_SALES: ClassVar[str] = 'sales'
    TYPE_SUPPORT: ClassVar[str] = 'support'

    id: Optional[int] = Field(default=None, primary_key=True)

    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    start_time: Optional[datetime] = Field(default=None)
    end_time: Optional[datetime] = Field(default=None)
    status: str = Field(default=STATUS_PLANNED, max_length=255)
    meeting_type: str = Field(max_length=255)

    # Foreign keys
    admin_id: int = Field(foreign_key='admin.id')
    contact_id: int = Field(foreign_key='contact.id')
    company_id: int = Field(foreign_key='company.id')
    deal_id: Optional[int] = Field(default=None, foreign_key='deal.id')

    # Relationships
    admin: Admin = Relationship(back_populates='meetings')
    contact: Contact = Relationship(back_populates='meetings')
    company: Company = Relationship(back_populates='meetings')
    deal: Optional[Deal] = Relationship(back_populates='meetings')

    @property
    def name(self):
        if self.meeting_type == Meeting.TYPE_SALES:
            return f'TutorCruncher demo with {self.admin.name}'
        else:
            return f'TutorCruncher support meeting with {self.admin.name}'

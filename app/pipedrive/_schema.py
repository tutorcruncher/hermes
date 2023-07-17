from typing import Optional

from pydantic import BaseModel

from app.models import Companies, Contacts, Deals, Meetings


def _remove_nulls(**kwargs):
    return {k: v for k, v in kwargs.items() if v is not None}


class Organisation(BaseModel):
    id: Optional[int] = None
    name: str
    address_country: str
    owner_id: Optional[int] = None

    # These are all custom fields
    estimated_income: str = ''
    status: str = ''
    website: str = ''
    paid_invoice_count: int = 0
    has_booked_call: bool = False
    has_signed_up: bool = False
    tc_profile_url: str = ''

    @classmethod
    async def from_company(cls, company: Companies):
        return cls(
            **_remove_nulls(
                name=company.name,
                owner_id=company.sales_person_id and (await company.sales_person).pd_owner_id,
                address_country=company.country,
                paid_invoice_count=company.paid_invoice_count,
                estimated_income=company.estimated_income,
                currency=company.currency,
                website=company.website,
                status=company.status,
                has_booked_call=company.has_booked_call,
                has_signed_up=company.has_signed_up,
                tc_profile_url=company.tc_cligency_url,
            )
        )


class Person(BaseModel):
    id: Optional[int] = None
    name: str
    owner_id: Optional[int] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address_country: Optional[str] = None
    org_id: Optional[int] = None

    @classmethod
    async def from_contact(cls, contact: Contacts):
        company: Companies = await contact.company
        return cls(
            name=contact.name,
            owner_id=company.sales_person_id and (await company.sales_person).pd_owner_id,
            email=contact.email,
            phone=contact.phone,
            address_country=contact.country,
            org_id=company.pd_org_id,
        )


class Activity(BaseModel):
    due_dt: str
    due_time: str
    subject: str
    user_id: int
    deal_id: Optional[int] = None
    person_id: Optional[int] = None
    org_id: Optional[int] = None

    @classmethod
    async def from_meeting(cls, meeting: Meetings):
        contact = await meeting.contact
        return cls(
            **_remove_nulls(
                **{
                    'due_dt': meeting.start_time.strftime('%Y-%m-%d'),
                    'due_time': meeting.start_time.strftime('%H:%M'),
                    'subject': meeting.name,
                    'user_id': (await meeting.admin).pd_owner_id,
                    'deal_id': meeting.deal_id and (await meeting.deal).pd_deal_id,
                    'person_id': contact.pd_person_id,
                    'org_id': (await contact.company).pd_org_id,
                }
            )
        )


class Deal(BaseModel):
    id: Optional[int] = None
    title: str
    org_id: int
    person_id: Optional[int] = None
    pipeline_id: int
    stage_id: int
    status: str

    @classmethod
    async def from_deal(cls, deal: Deals):
        company = deal.company_id and await deal.company
        contact = deal.contact_id and await deal.contact
        pipeline = await deal.pipeline
        pipeline_stage = await deal.pipeline_stage
        return cls(
            **_remove_nulls(
                title=deal.name,
                org_id=company and company.pd_org_id,
                user_id=(await deal.admin).pd_owner_id,
                person_id=contact and contact.pd_person_id,
                pipeline_id=pipeline.pd_pipeline_id,
                stage_id=pipeline_stage.pd_stage_id,
                status=deal.status,
            )
        )

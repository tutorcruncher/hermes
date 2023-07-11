from typing import Optional

from pydantic import BaseModel

from app.models import Companies, Contacts


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

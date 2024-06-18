from typing import Type

from tortoise.query_utils import Prefetch

from app.base_schema import HermesBaseModel
from app.models import Company, CustomField, CustomFieldValue, Deal, Admin
from app.tc2._schema import TCClient
from app.tc2.api import tc2_request


async def update_client_from_company(company: Company):
    """
    When an Organisation or Deal changes in Pipedrive, we want to update the Cligency obj in TC.
    """
    debug(company.__dict__)
    if cligency_id := company.tc2_cligency_id:
        tc_client = TCClient(**await tc2_request(f'clients/{cligency_id}/'))
        extra_attrs = {ea.machine_name: ea.value for ea in tc_client.extra_attrs}
        extra_attrs.update(pipedrive_url=company.pd_org_url)
        deal = await Deal.filter(company=company, status=Deal.STATUS_OPEN).first()
        if deal:
            extra_attrs.update(
                pipedrive_deal_stage=(await deal.stage).name, pipedrive_pipeline=(await deal.pipeline).name
            )
        custom_fields = await CustomField.filter(
            linked_object_type=Company.__name__, tc2_machine_name__not=''
        ).prefetch_related(Prefetch('values', queryset=CustomFieldValue.filter(company=company)))
        for cf in custom_fields:
            if cf.hermes_field_name:
                val = getattr(company, cf.hermes_field_name, None)
            else:
                val = cf.values[0].value if cf.values else None
            extra_attrs[cf.tc2_machine_name] = val # the error is happening here, as bdr person does not have a tc2_machine_name, as it is a meta_agency field not a custom field

        for ea in tc_client.extra_attrs:
            if ea.machine_name == 'termination_category':
                extra_attrs['termination_category'] = ea.value.replace(' ', '-')

        client_data = tc_client.model_dump()
        client_data['extra_attrs'] = extra_attrs

        # Update the admins
        if company.support_person:
            support_person = await company.support_person
            client_data['associated_admin'] = support_person.tc2_admin_id

        if company.bdr_person:
            bdr_person = await company.bdr_person
            client_data['bdr_person'] = bdr_person.tc2_admin_id

        if company.sales_person:
            sales_person = await company.sales_person
            client_data['sales_person'] = sales_person.tc2_admin_id

        await tc2_request('clients/', method='POST', data=client_data)


MODEL_TC2_LU = {Company: TCClient}


async def tc2_rebuild_schema_with_custom_fields() -> list[Type[HermesBaseModel]]:
    """
    Adds extra fields to the schema for the Pipedrive models based on CustomFields in the DB
    """
    # Since custom field data comes into TC2 as the `extra_attrs` field (which is a list of dicts), we can't add
    # the extra fields to the model as we do with PD models, which means we can't do validation but there we go.
    return []

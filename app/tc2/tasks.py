from typing import Type

from app.base_schema import get_custom_fieldinfo, HermesBaseModel
from app.models import Company, Deal, CustomField
from app.tc2._schema import TCClient
from app.tc2.api import tc2_request


async def update_client_from_company(company: Company):
    """
    When a deal changes in Pipedrive, we want to update the Cligency obj in TC.
    """
    if cligency_id := company.tc2_cligency_id:
        tc_client = TCClient(**await tc2_request(f'clients/{cligency_id}/'))
        extra_attrs = {ea.machine_name: ea.value for ea in tc_client.extra_attrs}
        extra_attrs.update(pipedrive_url=company.pd_org_url, pipedrive_id=company.pd_org_id)
        deal = await Deal.filter(company=company, status=Deal.STATUS_OPEN).first()
        if deal:
            extra_attrs.update(
                pipedrive_deal_stage=(await deal.stage).name, pipedrive_pipeline=(await deal.pipeline).name
            )
        client_data = tc_client.model_dump()
        client_data['extra_attrs'] = extra_attrs
        await tc2_request('clients/', method='POST', data=client_data)


MODEL_TC2_LU = {Company: TCClient}


async def tc2_rebuild_schema_with_custom_fields() -> list[Type[HermesBaseModel]]:
    models_to_rebuild = []
    for model, tc2_model in MODEL_TC2_LU.items():
        custom_fields = await CustomField.filter(linked_object_type=model.__name__)
        # First we reset the custom fields
        tc2_model.model_fields = {
            k: v for k, v in tc2_model.model_fields.items() if not (v.json_schema_extra or {}).get('custom')
        }
        for field in custom_fields:
            tc2_model.model_fields[field.machine_name] = await get_custom_fieldinfo(
                field, model, serialization_alias=field.tc2_machine_name, validation_alias=field.tc2_machine_name
            )
        models_to_rebuild.append(tc2_model)
    return models_to_rebuild

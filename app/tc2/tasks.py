from app.models import Deal, Company
from app.tc2.api import tc2_request


async def update_client_from_deal(deal: Deal):
    """
    When a deal changes in Pipedrive, we want to update the Cligency obj in TC.
    """
    company: Company = await deal.company
    if cligency_id := company.tc2_cligency_id:
        client_data = await tc2_request(f'clients/{cligency_id}/')
        extra_attrs = {f['machine_name']: f['value'] for f in client_data['extra_attrs']}
        extra_attrs.update(
            pipedrive_deal_stage=(await deal.stage).name,
            pipedrive_pipeline=(await deal.pipeline).name,
            pipedrive_url=company.pd_org_url,
        )
        client_data['extra_attrs'] = extra_attrs
        await tc2_request(f'clients/{cligency_id}/', method='POST', data=client_data)

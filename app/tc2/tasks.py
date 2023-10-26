from app.models import Company, Deal
from app.tc2._schema import TCClient
from app.tc2.api import tc2_request


async def update_client_from_company(company: Company):
    """
    When a deal changes in Pipedrive, we want to update the Cligency obj in TC.
    """
    if cligency_id := company.tc2_cligency_id:
        client_data = TCClient(**await tc2_request(f'clients/{cligency_id}/')).dict()
        extra_attrs = {
            f['machine_name']: f['value'].lower() if not f['value'].startswith('---') else ''
            for f in client_data['extra_attrs']
        }
        extra_attrs.update(pipedrive_url=company.pd_org_url, pipedrive_id=company.pd_org_id)
        deal = await Deal.filter(company=company, status=Deal.STATUS_OPEN).first()
        if deal:
            extra_attrs.update(
                pipedrive_deal_stage=(await deal.stage).name, pipedrive_pipeline=(await deal.pipeline).name
            )
        client_data['extra_attrs'] = extra_attrs
        await tc2_request('clients/', method='POST', data=client_data)

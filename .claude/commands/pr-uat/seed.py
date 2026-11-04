"""Seed the /pr-uat database with the rows `make setup` would fetch from Pipedrive. All of it is made up."""

from sqlmodel import select

from app.core.database import get_session
from app.main_app.models import Admin, Config, Pipeline, Stage

PIPELINES = {'payg': 1, 'startup': 2, 'enterprise': 3}


def main() -> None:
    with get_session() as db:
        if db.exec(select(Admin)).first():
            return
        stage = db.create(Stage(pd_stage_id=1, name='UAT entry stage'))
        pipelines = {
            name: db.create(Pipeline(pd_pipeline_id=pd_id, name=f'UAT {name}', dft_entry_stage_id=stage.id))
            for name, pd_id in PIPELINES.items()
        }
        db.create(
            Config(
                payg_pipeline_id=pipelines['payg'].id,
                startup_pipeline_id=pipelines['startup'].id,
                enterprise_pipeline_id=pipelines['enterprise'].id,
            )
        )
        db.create(
            Admin(
                first_name='Uat',
                last_name='Sales',
                username='uat-sales@example.org',
                tc2_admin_id=1,
                pd_owner_id=1,
                is_sales_person=True,
                is_support_person=True,
                is_bdr_person=True,
                sells_payg=True,
                sells_startup=True,
                sells_enterprise=True,
                sells_us=True,
                sells_gb=True,
                sells_au=True,
                sells_ca=True,
                sells_eu=True,
                sells_row=True,
            )
        )


if __name__ == '__main__':
    main()

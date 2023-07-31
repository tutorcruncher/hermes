import pytz
from fastapi_admin.app import app as admin_app
from fastapi_admin.enums import Method
from fastapi_admin.resources import Action, Field, Link, Model
from fastapi_admin.widgets import displays, inputs
from httpx import Request

from app.models import Admin, Config, Pipeline, Stage


@admin_app.register
class Dashboard(Link):
    label = 'Home'
    icon = 'fas fa-home'
    url = '/'


class TimezoneSelect(inputs.Select):
    async def get_options(self):
        return [(tz, tz) for tz in pytz.all_timezones]


@admin_app.register
class ConfigResource(Model):
    model = Config
    icon = 'fas fa-cogs'
    page_pre_title = page_title = label = 'Config'
    fields = [
        'meeting_dur_mins',
        'meeting_buffer_mins',
        'meeting_min_start',
        'meeting_max_end',
        Field('payg_pipeline_id', label='PAYG Pipeline', input_=inputs.ForeignKey(model=Pipeline)),
        Field('startup_pipeline_id', label='Startup Pipeline', input_=inputs.ForeignKey(model=Pipeline)),
        Field('enterprise_pipeline_id', label='Enterprise Pipeline', input_=inputs.ForeignKey(model=Pipeline)),
    ]

    async def get_toolbar_actions(self, request: Request):
        return []

    async def get_actions(self, request: Request) -> list[Action]:
        return [
            Action(label='Edit', icon='fa fa-edit', name='update', method=Method.GET, ajax=False),
        ]


@admin_app.register
class AdminResource(Model):
    model = Admin
    icon = 'fas fa-user'
    page_pre_title = page_title = label = 'Admins'
    fields = [
        Field('username', label='Email', input_=inputs.Email()),
        Field(name='password', label='Password', display=displays.InputOnly(), input_=inputs.Password()),
        Field('tc2_admin_id', label='TC admin id', input_=inputs.Number()),
        Field('pd_owner_id', label='Pipedrive owner ID', input_=inputs.Number()),
        'first_name',
        'last_name',
        Field('timezone', input_=TimezoneSelect()),
        Field('is_sales_person', label='Sales repr', input_=inputs.Switch()),
        Field('is_client_manager', label='Support repr (client manager)', input_=inputs.Switch()),
        Field('is_bdr_person', label='BDR', input_=inputs.Switch()),
    ]

    async def get_actions(self, request: Request) -> list[Action]:
        return [
            Action(label='Edit', icon='fa fa-edit', name='update', method=Method.GET, ajax=False),
            Action(label='Delete', icon='fa fa-trash', name='delete', method=Method.GET, ajax=False),
        ]


@admin_app.register
class PipelinesResource(Model):
    model = Pipeline
    icon = 'fas fa-random'
    page_pre_title = page_title = label = 'Pipelines'
    fields = [
        'id',
        'pd_pipeline_id',
        'name',
        Field('dft_entry_stage_id', label='Dft entry pipeline stage', input_=inputs.ForeignKey(model=Stage)),
    ]

    async def get_toolbar_actions(self, request: Request):
        return []

    async def get_actions(self, request: Request) -> list[Action]:
        return [
            Action(label='Edit', icon='fa fa-edit', name='update', method=Method.GET, ajax=False),
        ]


@admin_app.register
class StagesResource(Model):
    model = Stage
    icon = 'fas fa-tasks'
    page_pre_title = page_title = label = 'Stages'
    fields = ['id', 'name', 'pd_stage_id']

    async def get_toolbar_actions(self, request: Request):
        return []

    async def get_actions(self, request: Request):
        return []

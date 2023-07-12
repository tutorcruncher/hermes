from fastapi import Depends
from fastapi_admin.app import app as admin_app
from fastapi_admin.depends import get_resources
from fastapi_admin.template import templates


@admin_app.get('/')
async def home(request, resources=Depends(get_resources)):
    return templates.TemplateResponse(
        'dashboard.html',
        context={
            'request': request,
            'resources': resources,
            'resource_label': 'Dashboard',
            'page_pre_title': 'overview',
            'page_title': 'Dashboard',
        },
    )

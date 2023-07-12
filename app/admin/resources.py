from fastapi_admin.app import app as admin_app
from fastapi_admin.resources import Link, Model

from app.models import Admins


@admin_app.register
class Dashboard(Link):
    label = 'Home'
    icon = 'fas fa-home'
    url = '/'


@admin_app.register
class AdminResource(Model):
    model = Admins

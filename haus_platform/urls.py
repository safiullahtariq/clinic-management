"""
URL configuration for haus_platform project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from tenancy.views_dashboards import (
    universal_login_view,
    logout_view,
    member_dashboard_view,
    org_admin_dashboard_view,
    super_admin_dashboard_view
)

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Auth URLs
    path('login/', universal_login_view, name='login'),
    path('logout/', logout_view, name='logout'),

    # Role Dashboards
    path('dashboard/member/', member_dashboard_view, name='member_dashboard'),
    path('dashboard/org-admin/', org_admin_dashboard_view, name='org_admin_dashboard'),
    path('dashboard/super-admin/', super_admin_dashboard_view, name='super_admin_dashboard'),

    # App APIs & Pages
    path('', include('memberships.urls', namespace='memberships')),
    path('', include('tenancy.urls', namespace='tenancy')),
    path('', include('scheduling.urls', namespace='scheduling')),
    path('scheduling/', include('scheduling.urls')),
]

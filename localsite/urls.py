from django.conf import settings
from django.conf.urls import url, include
from django.conf.urls.static import static
from django.contrib import admin
from federal_common.generate_urls import generate_urls
from rest_framework import routers
import debug_toolbar
import elections
import parliaments
import proceedings
import re


def get_view_name(cls, suffix=None):
    if not hasattr(cls, "view_name"):
        if issubclass(cls, routers.APIRootView):
            with open("README.md", "r") as f:
                cls.view_name = f.readline()[1:]
        elif suffix == "List":
            return cls.queryset.model._meta.verbose_name_plural.title()
        elif suffix == "Instance":
            return cls.queryset.model._meta.verbose_name.title()
        else:
            raise Exception("Unexpected view suffix", suffix)
    return cls.view_name


def get_view_description(cls, html=False):
    if not hasattr(cls, "view_description"):
        if issubclass(cls, routers.APIRootView):
            with open("README.md", "r") as f:
                f.readline()  # Discard the first line (the title)
                cls.view_description = f.read()
        else:
            cls.view_description = re.sub("^ {8}", "", cls.queryset.model.__doc__, flags=re.MULTILINE)
    return cls.view_description


urlpatterns = generate_urls(
    proceedings.models,
    elections.models,
    parliaments.models,
)


if settings.DEBUG:
    urlpatterns.append(url(r"^admin/", admin.site.urls))
    urlpatterns.extend(static(settings.STATIC_URL, document_root=settings.STATIC_ROOT))
    urlpatterns.extend(static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT))
    urlpatterns = [url(r'^__debug__/', include(debug_toolbar.urls))] + urlpatterns

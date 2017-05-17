from django.conf import settings
from django.conf.urls import url, include
from django.conf.urls.static import static
from django.contrib import admin
from django.db.models import fields
from django.db.models.base import ModelBase
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django_extensions.db.fields.json import JSONField as JSONModelField
from elections import models
from rest_framework import filters
from rest_framework import serializers, viewsets, routers
from rest_framework.decorators import list_route, detail_route
from rest_framework.fields import JSONField as JSONSerializerField
from rest_framework.response import Response
from rest_framework_nested import routers as nested_routers


router = nested_routers.DefaultRouter()
nested_router_instances = []

model_serializers = {}
model_viewsets = {}

def get_view_name(cls, suffix=None):
    if issubclass(cls, routers.APIRootView):
        return "API Root"
    elif suffix == "List":
        return cls.queryset.model._meta.verbose_name_plural.title()
    elif suffix == "Instance":
        return cls.queryset.model._meta.verbose_name.title()
    else:
        raise Exception("Unexpected view suffix", suffix)

def get_view_description(cls, html=False):
    if issubclass(cls, routers.APIRootView):
        return """
            * Project source code: https://github.com/bradbeattie/canadian-parlimentarty-data
            * Database snapshot: https://github.com/bradbeattie/canadian-parlimentarty-data/raw/master/populated.sql.xz
            * Questions? [bradbeattie@gmail.com](mailto:bradbeattie@gmail.com)
        """
    else:
        return cls.queryset.model.__doc__

class ChoicesSerializerField(serializers.SerializerMethodField):
    def to_representation(self, value):
        return getattr(value, "get_{field_name}_display".format(field_name=self.field_name))()

for model_name in dir(models):
    model_class = getattr(models, model_name)
    if isinstance(model_class, ModelBase):
        class Serializer(serializers.HyperlinkedModelSerializer):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                for field in self.Meta.model._meta.local_fields:
                    if isinstance(field, JSONModelField):
                        self.fields[field.name] = JSONSerializerField()
                    elif field.choices:
                        self.fields[field.name] = ChoicesSerializerField()
                for field in self.Meta.model._meta.get_fields():
                    if field not in self.Meta.model._meta.local_fields:
                        self.fields[field.name] = serializers.HyperlinkedIdentityField(
                            view_name="{}-{}-list".format(
                                str(slugify(self.Meta.model._meta.verbose_name)),
                                str(slugify(field.related_model._meta.verbose_name_plural)),
                            ),
                            lookup_url_kwarg=field.remote_field.name.replace("_rel_+", "") + "_pk",  # TODO: This feels hacky. What's the proper approach?
                        )

            class Meta:
                model = model_class
                fields = [
                    field.name
                    for field in model_class._meta.local_fields
                ]

        # ViewSets define the view behavior.
        class ViewSet(viewsets.ModelViewSet):
            queryset = model_class.objects.all()
            serializer_class = Serializer
            filter_backends = (filters.SearchFilter, filters.DjangoFilterBackend)

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.search_fields = [
                    field.name
                    for field in self.queryset.model._meta.local_fields
                    if isinstance(field, fields.CharField)
                ]
                self.filter_fields = [
                    field.name
                    for field in self.queryset.model._meta.local_fields
                    if not isinstance(field, fields.files.FileField)
                ]

            def filter_queryset(self, *args, **kwargs):
                queryset = super().filter_queryset(*args, **kwargs)
                queryset = queryset.filter(**{
                    k.replace("_pk", ""): v  # TODO: This feels hacky. What's the proper approach?
                    for k, v in self.kwargs.items()
                })
                return queryset

        model_serializers[model_name] = Serializer
        model_viewsets[model_name] = ViewSet
        router.register(str(slugify(model_class._meta.verbose_name_plural)), ViewSet)

for model_name in dir(models):
    model_class = getattr(models, model_name)
    if isinstance(model_class, ModelBase):
        for field in model_class._meta.get_fields():
            if field not in model_class._meta.local_fields:
                nested_router = nested_routers.NestedSimpleRouter(
                    router,
                    str(slugify(model_class._meta.verbose_name_plural)),
                    lookup=field.remote_field.name.replace("_rel_+", ""),  # TODO: This feels hacky. What's the proper approach?
                )
# TODO: Not sure this is handling party geographic and party historic relationships properly
                nested_router.register(
                    str(slugify(field.related_model._meta.verbose_name_plural)),
                    model_viewsets[field.related_model._meta.object_name],
                    base_name="-".join((
                        str(slugify(model_class._meta.verbose_name)),
                        str(slugify(field.related_model._meta.verbose_name_plural)),
                    )),
                )
                nested_router_instances.append(nested_router)

urlpatterns = [
    url(r"^", include(router.urls)),
    *[
        url(r"^", include(nested_router.urls))
        for nested_router in nested_router_instances
    ]
]

if settings.DEBUG:
    urlpatterns.append(url(r"^admin/", admin.site.urls))
    urlpatterns.extend(static(settings.STATIC_URL, document_root=settings.STATIC_ROOT))
    urlpatterns.extend(static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT))

from django.conf.urls import url, include
from django.db.models import fields
from django.db.models.base import ModelBase
from django.utils.text import slugify
from django_extensions.db.fields.json import JSONField as JSONModelField
from rest_framework import filters
from rest_framework import serializers, viewsets
from rest_framework.fields import JSONField as JSONSerializerField
from rest_framework_nested import routers as nested_routers
import django_filters
import re


COMPARISONS = set(["exact", "gt", "gte", "lt", "lte"])
REL_MATCH = re.compile(r"[_-]rel[_-]\+")


class ChoicesSerializerField(serializers.SerializerMethodField):
    def to_representation(self, value):
        return getattr(value, "get_{field_name}_display".format(field_name=self.field_name))()


def prep(*args):
    return slugify("-".join(
        REL_MATCH.sub("", str(arg))
        for arg in args
    ))


def get_field_lookups(field):
    lookups = set(["exact"])
    if isinstance(field, (fields.CharField, JSONModelField)):
        lookups.update(set([
            "contains", "icontains",
            "regex", "iregex",
            "startswith", "istartswith",
            "endswith", "iendswith",
        ]))
    if isinstance(field, (fields.DecimalField, fields.IntegerField, fields.DateField)):
        lookups.update(COMPARISONS)
    if isinstance(field, fields.DateField):
        for prefix in ("year", "month", "day", "week", "week_day"):
            lookups.update(
                "__".join(filter(None, (prefix, comparison)))
                for comparison in COMPARISONS
            )
    if isinstance(field, fields.DateTimeField):
        for prefix in ("hour", "minute", "second"):
            lookups.update(
                "__".join(filter(None, (prefix, comparison)))
                for comparison in COMPARISONS
            )
    return lookups


def generate_urls(*model_sets):
    router = nested_routers.DefaultRouter()
    nested_router_instances = []
    model_viewsets = {}

    for models in model_sets:
        for model_name in dir(models):
            model_class = getattr(models, model_name)
            if isinstance(model_class, ModelBase) and "Mixin" not in model_name:
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
                                field_kwargs = {
                                    "view_name": prep(
                                        self.Meta.model._meta.verbose_name,
                                        field.related_query_name().replace("_", "-") if field.related_query_name else field.related_model._meta.verbose_name_plural,
                                        "list",
                                    ),
                                    "lookup_url_kwarg": field.remote_field.name.replace("_rel_+", "") + "_pk",  # TODO: This feels hacky. What's the proper approach?
                                }
                                self.fields[field.name] = serializers.HyperlinkedIdentityField(**field_kwargs)

                    class Meta:
                        model = model_class
                        fields = ["url"] + [
                            field.name
                            for field in model_class._meta.local_fields
                        ]

                class Filter(django_filters.FilterSet):
                    class Meta:
                        model = model_class
                        fields = {
                            field.name: get_field_lookups(field)
                            for field in model_class._meta.local_fields
                            if not isinstance(field, fields.related.RelatedField) and not isinstance(field, fields.files.FileField)
                        }

                # ViewSets define the view behavior.
                class ViewSet(viewsets.ModelViewSet):
                    queryset = model_class.objects.all()
                    serializer_class = Serializer
                    filter_backends = (filters.SearchFilter, filters.DjangoFilterBackend)
                    filter_class = Filter

                    def __init__(self, *args, **kwargs):
                        super().__init__(*args, **kwargs)
                        self.search_fields = [
                            field.name
                            for field in self.queryset.model._meta.local_fields
                            if isinstance(field, fields.CharField)
                        ]

                    def filter_queryset(self, *args, **kwargs):
                        queryset = super().filter_queryset(*args, **kwargs)
                        queryset = queryset.filter(**{
                            k.replace("_pk", ""): v  # TODO: This feels hacky. What's the proper approach?
                            for k, v in self.kwargs.items()
                        })
                        return queryset

                model_viewsets[model_name] = ViewSet
                router.register(str(slugify(model_class._meta.verbose_name_plural)), ViewSet)

    for models in model_sets:
        for model_name in dir(models):
            model_class = getattr(models, model_name)
            if isinstance(model_class, ModelBase) and "Mixin" not in model_name:
                for field in model_class._meta.get_fields():
                    if field not in model_class._meta.local_fields:
                        nested_router_kwargs = {
                            "parent_router": router,
                            "parent_prefix": prep(model_class._meta.verbose_name_plural),
                            "lookup": prep(field.remote_field.name),
                        }
                        prefix = prep(field.related_query_name() if field.related_query_name else field.related_model._meta.verbose_name_plural).replace("_", "-")
                        register_kwargs = {
                            "prefix": prefix,
                            "viewset": model_viewsets[field.related_model._meta.object_name],
                            "base_name": prep(model_class._meta.verbose_name, prefix),
                        }
                        nested_router = nested_routers.NestedSimpleRouter(**nested_router_kwargs)
                        nested_router.register(**register_kwargs)
                        nested_router_instances.append(nested_router)

    return [
        url(r"^", include(router.urls)),
        *[
            url(r"^", include(nested_router.urls))
            for nested_router in nested_router_instances
        ]
    ]

from django.db.models import fields
from django.conf.urls import url, include
from django.db.models.base import ModelBase
from django.utils.text import slugify
from django_extensions.db.fields.json import JSONField as JSONModelField
from rest_framework import filters
from rest_framework import serializers, viewsets
from rest_framework.fields import JSONField as JSONSerializerField
from rest_framework_nested import routers as nested_routers


class ChoicesSerializerField(serializers.SerializerMethodField):
    def to_representation(self, value):
        return getattr(value, "get_{field_name}_display".format(field_name=self.field_name))()


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
                            if not isinstance(field, fields.related.RelatedField)
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
                        nested_router = nested_routers.NestedSimpleRouter(
                            router,
                            str(slugify(model_class._meta.verbose_name_plural)),
                            lookup=field.remote_field.name.replace("_rel_+", ""),  # TODO: This feels hacky. What's the proper approach?
                        )
        # TODO: Not sure this is handling party geographic and party historic relationships properly
            #"related_historically": "http://localhost:8000/ridings/387/ridings/",
            #"related_geographically": "http://localhost:8000/ridings/387/ridings/"
                        nested_router.register(
                            str(slugify(field.related_model._meta.verbose_name_plural)),
                            model_viewsets[field.related_model._meta.object_name],
                            base_name="-".join((
                                str(slugify(model_class._meta.verbose_name)),
                                str(slugify(field.related_model._meta.verbose_name_plural)),
                            )),
                        )
                        nested_router_instances.append(nested_router)

    return [
        url(r"^", include(router.urls)),
        *[
            url(r"^", include(nested_router.urls))
            for nested_router in nested_router_instances
        ]
    ]

from django.db import models
from django_extensions.db.fields import json
from federal_common.sources import EN, FR


class LinksMixin(models.Model):
    links = json.JSONField()

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.links = self.links or {EN: {}, FR: {}}


class NamesMixin(models.Model):
    slug = models.SlugField(max_length=200, primary_key=True)
    names = json.JSONField()

    class Meta:
        abstract = True

    def __str__(self):
        return self.slug

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.names = self.names or {EN: {}, FR: {}}

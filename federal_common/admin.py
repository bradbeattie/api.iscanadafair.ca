from django.db.models.fields import AutoField
from federal_common.sources import EN, FR
from django.utils.safestring import mark_safe
from django.core import urlresolvers
from django.contrib import admin
from django.db.models.fields.related import ForeignKey
from django.utils.html import format_html, format_html_join


class CommonAdmin(admin.ModelAdmin):
    def lookup_allowed(self, key, value):
        return True


class CommonInline(admin.TabularInline):
    extra = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields = list(
            [
                "{}{}".format(field.name, "_link" if isinstance(field, ForeignKey) or isinstance(field, AutoField) else "")
                for field in self.opts.local_fields
            ] + [
                field.name
                for field in self.opts.local_many_to_many
            ]
        )
        self.readonly_fields = self.fields

        def make_field_link(field):
            if isinstance(field, ForeignKey):
                def _method(obj):
                    attr = getattr(obj, "{}_id".format(field.name))
                    if attr is None:
                        return attr
                    else:
                        pattern_name = 'admin:{}_{}_change'.format(
                            field.related_model.__module__.split(".")[0],
                            field.related_model._meta.model_name,
                        )
                        change_url = urlresolvers.reverse(pattern_name, args=[attr])
                        return mark_safe('<a href="%s">%s</a>' % (change_url, getattr(obj, field.name)))
            else:
                def _method(obj):
                    pattern_name = 'admin:{}_{}_change'.format(
                        self.model.__module__.split(".")[0],
                        self.model._meta.model_name,
                    )
                    change_url = urlresolvers.reverse(pattern_name, args=[getattr(obj, "{}".format(field.name))])
                    return mark_safe('<a href="%s">%s</a>' % (change_url, getattr(obj, field.name)))
            return _method
        for field in self.opts.local_fields:
            if isinstance(field, ForeignKey) or isinstance(field, AutoField):
                field_link = make_field_link(field)
                field_link.short_description = field.name
                setattr(self, "{}_link".format(field.name), field_link)

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class HasNames(object):
    def show_names(self, obj):
        return format_html("""
            <h5>English</h5>
            <dl>{}</dl>
            <h5>Français</h5>
            <dl>{}</dl>
        """, format_html_join("", "<dt>{}</dt><dd>{}</dd>", (
            (source, name)
            for source, name in obj.names[EN].items()
        )), format_html_join("", "<dt>{}</dt><dd>{}</dd>", (
            (source, name)
            for source, name in obj.names[FR].items()
        )))

    search_fields = ("slug", "names")


class HasLinks(object):
    def show_links(self, obj):
        return format_html("""
            <h5>English</h5>
            <ul>{}</ul>
            <h5>Français</h5>
            <ul>{}</ul>
        """, format_html_join("", "<li><a href='{}'>{}</a></li>", (
            (link, source)
            for source, link in obj.links[EN].items()
        )), format_html_join("", "<li><a href='{}'>{}</a></li>", (
            (link, source)
            for source, link in obj.links[FR].items()
        )))

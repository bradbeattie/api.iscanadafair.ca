from django.conf import settings
from django.db.models.fields import AutoField
from django.utils.safestring import mark_safe
from django.core import urlresolvers
from django.contrib import admin
from django.contrib.admin.utils import flatten_fieldsets
from django.db.models.fields.related import ForeignKey
from django.utils.html import format_html, format_html_join
from elections import models


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
                        pattern_name = 'admin:elections_{}_change'.format(field.related_model._meta.model_name)
                        change_url = urlresolvers.reverse(pattern_name, args=[attr])
                        return mark_safe('<a href="%s">%s</a>' % (change_url, getattr(obj, field.name)))
            else:
                def _method(obj):
                    pattern_name = 'admin:elections_{}_change'.format(self.model._meta.model_name)
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


class HasNameVariants(object):
    def show_name_variants(self, obj):
        return format_html("<dl>{}</dl>", format_html_join("", "<dt>{}</dt><dd>{}</dd>", (
            (source, name)
            for source, name in obj.name_variants.items()
        )))


class HasLinks(object):
    def show_links(self, obj):
        return format_html("<ul>{}</ul>", format_html_join("", "<li><a href='{}'>{}</a></li>", (
            (link, source)
            for source, link in obj.links.items()
        )))


class ElectionCandidateInline(CommonInline):
    model = models.ElectionCandidate
class ElectionRidingInline(CommonInline):
    model = models.ElectionRiding



class SessionAdmin(HasLinks, CommonAdmin):
    list_display = ("parliament", "number", "date_start", "date_end", "show_links")
    list_filter = ("parliament", )
admin.site.register(models.Session, SessionAdmin)


class ProvinceAdmin(HasNameVariants, HasLinks, CommonAdmin):
    list_display = ("name", "show_name_variants", "elections", "show_links")
    list_filter = ("ridings__election_ridings__general_election", )

    def elections(self, obj):
        return ", ".join(map(
            lambda x: str(x),
            sorted(
                models.GeneralElection.objects.filter(
                    election_ridings__riding__province=obj,
                ).distinct().values_list("number", flat=True)
            )
        ))
admin.site.register(models.Province, ProvinceAdmin)


class ElectionAdmin(HasLinks, CommonAdmin):
    list_display = ("number", "date_end", "show_links", "population", "registered", "ballots_total", "turnout")
admin.site.register(models.GeneralElection, ElectionAdmin)


class ParliamentAdmin(HasLinks, CommonAdmin):
    list_display = ("number", "government_party", "color_swatch", "show_links")

    def color_swatch(self, obj):
        if obj.government_party:
            return obj.government_party.color_swatch()
admin.site.register(models.Parliament, ParliamentAdmin)


class PartyAdmin(HasNameVariants, HasLinks, CommonAdmin):
    list_display = ("name", "color_swatch", "show_name_variants", "show_links", "elections")
    list_filter = ("election_candidates__election_riding__general_election", )
    search_fields = ("name", "name_variants")

    def elections(self, obj):
        return ", ".join(map(
            lambda x: str(x),
            sorted(
                models.GeneralElection.objects.filter(
                    election_ridings__election_candidates__party=obj,
                ).distinct().values_list("number", flat=True)
            )
        ))
admin.site.register(models.Party, PartyAdmin)


class ParliamentarianAdmin(HasNameVariants, HasLinks, CommonAdmin):
    list_display = ("name", "show_name_variants", "show_links", "elections", "show_photo")
    list_filter = ("election_candidates__election_riding__general_election", )
    search_fields = ("name", )
    inlines = (ElectionCandidateInline, )

    def show_photo(self, obj):
        if obj.photo:
            return format_html("<img src='{}{}' />", settings.MEDIA_URL, obj.photo)

    def elections(self, obj):
        return ", ".join(map(
            lambda x: str(x),
            sorted(
                models.GeneralElection.objects.filter(
                    election_ridings__election_candidates__parliamentarian=obj,
                ).distinct().values_list("number", flat=True)
            )
        ))
admin.site.register(models.Parliamentarian, ParliamentarianAdmin)


class RidingAdmin(HasNameVariants, HasLinks, CommonAdmin):
    list_display = ("name", "province", "show_name_variants", "show_links", "elections")
    search_fields = ("name", )
    list_filter = ("province", "election_ridings__general_election")
    filter_horizontal = ("related_geographically", "related_historically")
    inlines = (ElectionRidingInline, )

    def elections(self, obj):
        return ", ".join(map(
            lambda x: str(x),
            sorted(
                models.GeneralElection.objects.filter(
                    election_ridings__riding=obj,
                ).distinct().values_list("number", flat=True)
            )
        ))
admin.site.register(models.Riding, RidingAdmin)


class ElectionRidingAdmin(HasLinks, CommonAdmin):
    list_display = ("riding", "date", "show_links", "population", "registered")
    search_fields = ("general_election__number", "riding__name")
    list_filter = ("general_election", "riding__province")
    inlines = (ElectionCandidateInline, )
admin.site.register(models.ElectionRiding, ElectionRidingAdmin)


class ElectionCandidateAdmin(CommonAdmin):
    raw_id_fields = ("election_riding", "parliamentarian")
    list_display = ("name", "parliamentarian", "election_riding", "party", "color_swatch", "profession", "ballots", "ballots_percentage", "elected", "acclaimed", "show_photo")
    list_filter = ("elected", "acclaimed", "election_riding__general_election", "election_riding__riding__province")
    search_fields = ("election_riding__general_election__number", "election_riding__riding__name", "name", "parliamentarian__name", "party__name", "party__name_variants")

    def show_photo(self, obj):
        if obj.parliamentarian and obj.parliamentarian.photo:
            return format_html("<img src='{}{}' />", settings.MEDIA_URL, obj.parliamentarian.photo)

    def color_swatch(self, obj):
        if obj.party:
            return obj.party.color_swatch()
admin.site.register(models.ElectionCandidate, ElectionCandidateAdmin)


class CommitteeAdmin(HasLinks, CommonAdmin):
    list_display = ("code", "name", "chamber", "show_links")
    search_fields = ("code", "name")
    list_filter = ("chamber", )
admin.site.register(models.Committee, CommitteeAdmin)


class BillAdmin(HasLinks, CommonAdmin):
    list_display = ("code_letter", "code_number", "session", "title")
    search_fields = ("code_letter", "code_number", "title")
    list_filter = ("code_letter", "session__parliament")
    filter_horizontal = ("committees", )
admin.site.register(models.Bill, BillAdmin)


class SittingAdmin(CommonAdmin):
    list_display = ("session", "number", "date")
    list_filter = ("session__parliament", )
admin.site.register(models.Sitting, SittingAdmin)


class SittingVoteAdmin(HasLinks, CommonAdmin):
    list_display = ("sitting", "number", "bill", "show_links")
    raw_id_fields = ("bill", "sitting")
    list_filter = ("sitting__session__parliament", )
admin.site.register(models.SittingVote, SittingVoteAdmin)


class SittingVoteParticipantAdmin(CommonAdmin):
    list_display = ("sitting_vote", "parliamentarian", "party", "recorded_vote")
    list_filter = ("recorded_vote", "sitting_vote__sitting__session__parliament", )
    search_fields = ("parliamentarian__name", )
    raw_id_fields = ("sitting_vote", "parliamentarian")
admin.site.register(models.SittingVoteParticipant, SittingVoteParticipantAdmin)

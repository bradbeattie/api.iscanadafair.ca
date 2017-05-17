from django.conf import settings
from django.utils.html import format_html
from federal_common.admin import CommonAdmin, CommonInline, HasLinks
from django.contrib import admin
from elections import models


class GeneralElectionAdmin(HasLinks, CommonAdmin):
    list_display = ("number", "parliament", "date", "show_links", "population", "registered", "ballots_total", "turnout")


class ByElectionAdmin(HasLinks, CommonAdmin):
    list_display = ("date", "parliament", "show_links")
    list_filter = ("parliament", "date")
    search_fields = ("date", )


class ElectionCandidateInline(CommonInline):
    model = models.ElectionCandidate


class ElectionRidingAdmin(CommonAdmin):
    list_display = ("riding", "date", "population", "registered")
    search_fields = ("general_election__number", "riding__slug")
    list_filter = ("general_election", "riding__province")
    inlines = (ElectionCandidateInline, )


class ElectionCandidateAdmin(CommonAdmin):
    raw_id_fields = ("election_riding", "parliamentarian")
    list_display = ("name", "parliamentarian", "election_riding", "party", "color_swatch", "profession", "ballots", "ballots_percentage", "elected", "acclaimed", "show_photo")
    list_filter = ("elected", "acclaimed", "election_riding__general_election", "election_riding__riding__province")
    search_fields = ("election_riding__general_election__number", "election_riding__riding__slug", "name", "parliamentarian__slug", "party__slug", "party__names")

    def show_photo(self, obj):
        if obj.parliamentarian and obj.parliamentarian.photo:
            return format_html("<img src='{}{}' />", settings.MEDIA_URL, obj.parliamentarian.photo)

    def color_swatch(self, obj):
        if obj.party:
            return obj.party.color_swatch()


admin.site.register(models.GeneralElection, GeneralElectionAdmin)
admin.site.register(models.ByElection, ByElectionAdmin)
admin.site.register(models.ElectionCandidate, ElectionCandidateAdmin)
admin.site.register(models.ElectionRiding, ElectionRidingAdmin)

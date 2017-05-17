from django.conf import settings
from django.utils.html import format_html
from federal_common.admin import CommonAdmin, HasLinks, HasNames
from django.contrib import admin
from parliaments import models


class ProvinceAdmin(HasNames, HasLinks, CommonAdmin):
    list_display = ("slug", "show_names", "show_links")
    list_filter = ("ridings__election_ridings__general_election", )
    search_fields = ("slug", "names")


class ParliamentAdmin(HasLinks, CommonAdmin):
    list_display = ("number", "government_party", "color_swatch", "show_links")

    def color_swatch(self, obj):
        if obj.government_party:
            return obj.government_party.color_swatch()


class SessionAdmin(HasLinks, CommonAdmin):
    list_display = ("parliament", "number", "date_start", "date_end", "show_links")
    list_filter = ("parliament", )


class PartyAdmin(HasNames, HasLinks, CommonAdmin):
    list_display = ("slug", "color_swatch", "show_names", "show_links")
    list_filter = ("election_candidates__election_riding__general_election", )
    search_fields = ("slug", "names")
    filter_horizontal = ("related", )


class ParliamentarianAdmin(HasNames, HasLinks, CommonAdmin):
    list_display = ("slug", "show_names", "show_links", "show_photo")
    list_filter = ("election_candidates__election_riding__general_election", )
    search_fields = ("slug", "names")

    def show_photo(self, obj):
        if obj.photo:
            return format_html("<img src='{}{}' />", settings.MEDIA_URL, obj.photo)


class RidingAdmin(HasNames, HasLinks, CommonAdmin):
    list_display = ("slug", "province", "show_names", "show_links")
    list_filter = ("province", "election_ridings__general_election")
    filter_horizontal = ("related_geographically", "related_historically")
    search_fields = ("slug", "names")


admin.site.register(models.Session, SessionAdmin)
admin.site.register(models.Parliament, ParliamentAdmin)
admin.site.register(models.Parliamentarian, ParliamentarianAdmin)
admin.site.register(models.Party, PartyAdmin)
admin.site.register(models.Province, ProvinceAdmin)
admin.site.register(models.Riding, RidingAdmin)

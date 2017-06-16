from federal_common.admin import CommonAdmin, HasLinks, HasNames
from django.utils.text import mark_safe
from federal_common.sources import EN
from django.contrib import admin
from proceedings import models


class SittingAdmin(HasLinks, CommonAdmin):
    list_display = ("slug", "date", "session", "show_links")
    list_filter = ("session__parliament", )
    search_fields = ("slug", )


class CommitteeAdmin(HasNames, HasLinks, CommonAdmin):
    list_display = ("slug", "show_names", "chamber", "show_links")
    list_filter = ("chamber", "session__parliament")


class BillAdmin(HasNames, HasLinks, CommonAdmin):
    list_display = ("slug", "show_names", "session", "show_links")
    list_filter = ("session__parliament", )
    filter_horizontal = ("committees", )
    search_fields = ("slug", )


class RecordingAdmin(HasNames, HasLinks, CommonAdmin):
    list_display = ("slug", "show_names")
    list_filter = ("category", "status")
    search_fields = ("slug", )
    raw_id_fields = ("sitting", )


class HansardBlockAdmin(HasNames, HasLinks, CommonAdmin):
    list_display = ("slug", "sitting", "get_category_display", "show_metadata_en", "show_content_en")
    list_filter = ("category", "sitting__session__parliament")
    search_fields = ("slug", )
    raw_id_fields = ("sitting", "previous", "house_vote", "parliamentarian")

    def show_content_en(self, obj):
        return mark_safe(obj.content.get(EN, None))

    def show_metadata_en(self, obj):
        return mark_safe("""<table>{}</table>""".format("".join(
            """<tr><th>{}</th><td>{}</td></tr>""".format(k, v.get(EN, "UNKNOWN!") if isinstance(v, dict) else v)
            for k, v in obj.metadata.items()
        )))


class HouseVoteAdmin(HasLinks, CommonAdmin):
    list_display = ("slug", "show_links", "show_context")
    raw_id_fields = ("bill", )
    list_filter = ("sitting__session__parliament", )

    def show_context(self, obj):
        return obj.context.get(EN, None)


class HouseVoteParticipantAdmin(CommonAdmin):
    list_display = ("house_vote", "parliamentarian", "party", "recorded_vote")
    list_filter = ("recorded_vote", "house_vote__sitting__session__parliament")
    search_fields = ("parliamentarian__slug", "parliamentarian__names")
    raw_id_fields = ("house_vote", "parliamentarian")


admin.site.register(models.Bill, BillAdmin)
admin.site.register(models.Committee, CommitteeAdmin)
admin.site.register(models.Sitting, SittingAdmin)
admin.site.register(models.Recording, RecordingAdmin)
admin.site.register(models.HouseVote, HouseVoteAdmin)
admin.site.register(models.HansardBlock, HansardBlockAdmin)
admin.site.register(models.HouseVoteParticipant, HouseVoteParticipantAdmin)

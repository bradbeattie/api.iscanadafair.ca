from federal_common.admin import CommonAdmin, HasLinks, HasNames
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
admin.site.register(models.HouseVoteParticipant, HouseVoteParticipantAdmin)

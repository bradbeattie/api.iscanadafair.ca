from federal_common.admin import CommonAdmin, HasLinks, HasNames
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


# class VoteAdmin(HasLinks, CommonAdmin):
#     list_display = ("number", "bill", "show_links")
#     raw_id_fields = ("bill", )
#     list_filter = ("session__parliament", )
#
#
# class VoteParticipantAdmin(CommonAdmin):
#     list_display = ("vote", "parliamentarian", "party", "recorded_vote")
#     list_filter = ("recorded_vote", "vote__session__parliament")
#     search_fields = ("parliamentarian__slug", "parliamentarian__names")
#     raw_id_fields = ("vote", "parliamentarian")


admin.site.register(models.Bill, BillAdmin)
admin.site.register(models.Committee, CommitteeAdmin)
admin.site.register(models.Sitting, SittingAdmin)
admin.site.register(models.Recording, RecordingAdmin)
# admin.site.register(models.Vote, VoteAdmin)
# admin.site.register(models.VoteParticipant, VoteParticipantAdmin)

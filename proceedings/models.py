from django.db import models
from federal_common.models import NamesMixin, LinksMixin
from parliaments import models as parliament_models


class Committee(NamesMixin, LinksMixin, models.Model):
    """
        ## Data sources

        * Parliament publishes bills through LEGISinfo, including committee data: http://www.parl.gc.ca/LegisInfo/
        * Parliament lists parsable data from the 36th parliament onwards: http://www.parl.gc.ca/Committees/en/List?parl=36&session=1
    """
    CHAMBER_HOC = 1
    CHAMBER_SEN = 2
    CHAMBER_JOINT = 3
    session = models.ForeignKey(parliament_models.Session, related_name="committees")
    chamber = models.PositiveSmallIntegerField(choices=(
        (CHAMBER_HOC, "House of Commons"),
        (CHAMBER_SEN, "Senate"),
        (CHAMBER_JOINT, "Joint committee"),
    ))

    class Meta:
        ordering = ("slug", )


class Bill(NamesMixin, LinksMixin, models.Model):
    """
        ## Data sources

        * Parliament lists recent bills at LEGISinfo: http://www.parl.gc.ca/LegisInfo/

        ## Filtering examples

        * [Bills from the 42nd parliament](?slug__startswith=42)
        * [Bills from the 42nd parliament's 1st session](/sessions/42-1/bills/)
        * [Bills from the senate](?slug__contains=s)
        * [Bills that mention Vancouver](?names__icontains=vancouver)
    """
    session = models.ForeignKey(parliament_models.Session, related_name="bills")
    committees = models.ManyToManyField(Committee, related_name="bills")

    class Meta:
        ordering = ("slug", )


# class Recording(NamesMixin, LinksMixin, models.Model):
#     """
#         ## Data sources
#
#         * http://parlvu.parl.gc.ca/
#     """
#     CATEGORY_AUDIO_ONLY = 1
#     CATEGORY_TELEVISED = 2
#     CATEGORY_IN_CAMERA = 2
#     CATEGORY_NO_BROADCAST = 3
#     CATEGORY_TRAVEL = 4
#     STATUS_ADJOURNED = 1
#     STATUS_CANCELLED = 2
#     STATUS_NOT_STARTED = 3
#
#     scheduled_start = models.DateTimeField()
#     scheduled_end = models.DateTimeField()
#     actual_start = models.DateTimeField(null=True)
#     actual_end = models.DateTimeField(null=True)
#     location = models.CharField(max_length=200)
#     category = models.PositiveSmallIntegerField(choices=(
#         (CATEGORY_AUDIO_ONLY, "Audio only"),
#         (CATEGORY_TELEVISED, "Televised"),
#         (CATEGORY_IN_CAMERA, "In Camera"),
#         (CATEGORY_NO_BROADCAST, "No Broadcast"),
#         (CATEGORY_TRAVEL, "Travel"),
#     ))
#     status = models.PositiveSmallIntegerField(choices=(
#         (STATUS_ADJOURNED, "Adjourned"),
#         (STATUS_CANCELLED, "Cancelled"),
#         (STATUS_NOT_STARTED, "Not Started"),
#     ))
#
#     class Meta:
#         ordering = ("slug", )


# class CommitteeMeeting(models.Model):
#     """
#         ## Data sources
#
#         * http://www.parl.gc.ca/Committees/en/FilteredMeetings?meetingDate=2017-05-03
#     """
#     pass


# class Vote(models.Model):
#     """
#         ## Data sources
#
#         * Parliament publishes votes since the 38th parliament: http://www.parl.gc.ca/housechamberbusiness/ChamberVoteList.aspx
#     """
#     session = models.ForeignKey(parliament_models.Session, related_name="votes")
#     number = models.PositiveSmallIntegerField(db_index=True)
#     bill = models.ForeignKey(Bill, blank=True, null=True, related_name="votes")
#     context = json.JSONField()
#     links = json.JSONField()
#
#     class Meta:
#         unique_together = ("session", "number")
#
#     def __str__(self):
#         return "{}, Vote {}".format(self.sitting, self.number)
#
#
# class VoteParticipant(models.Model):
#     """
#         ## Data sources
#
#         * Parliament publishes votes and vote details since the 38th parliament: http://www.parl.gc.ca/housechamberbusiness/ChamberVoteList.aspx
#           * Additionally, votes come with party affilliation which is useful in tracking party affiliation when MPs switch between elections.
#     """
#     VOTE_NAY = 1
#     VOTE_YEA = 2
#     VOTE_PAIRED = 3
#     VOTE_ABSTAINED = 4
#
#     vote = models.ForeignKey(Vote, related_name="vote_participants")
#     parliamentarian = models.ForeignKey(parliament_models.Parliamentarian, related_name="vote_participants")
#     party = models.ForeignKey(parliament_models.Party, related_name="vote_participants", null=True)
#     recorded_vote = models.PositiveSmallIntegerField(choices=(
#         (VOTE_NAY, "Nay"),
#         (VOTE_YEA, "Yea"),
#         (VOTE_PAIRED, "Paired"),
#         (VOTE_ABSTAINED, "Abstained"),
#     ))
#
#     class Meta:
#         unique_together = ("vote", "parliamentarian")
#
#     def __str__(self):
#         return "{}, {}, {}".format(self.sitting_vote, self.parliamentarian, self.get_recorded_vote_display())

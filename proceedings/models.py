from django.db import models
from django_extensions.db.fields import json
from federal_common.models import NamesMixin, LinksMixin
from parliaments import models as parliament_models


class Recording(NamesMixin, LinksMixin, models.Model):
    """
        ## Data sources

        * [ParlVU (39th Parliament onwards)](http://parlvu.parl.gc.ca/)

        ## Notes

        * OurCommons and ParlVU don't always agree. I've identified the following inconsistencies and contacted infonet@parl.gc.ca. I'm currently waiting on a response.
          * ParlVU speaks of [HoC Sitting No. 130 (2014-10-22)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20141022/-1/13793), but OurCommons thinks no session exists on this date and [#130 is on 2014-10-23](http://www.ourcommons.ca/DocumentViewer/en/41-2/house/sitting-130/order-notice).
          * ParlVU speaks of [HoC Sitting No. A-35 (2013-12-11)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20131211/-1/13665), but OurCommons thinks no session exists on this date and #35A doesn't exist.
          * ParlVU speaks of [HoC Sitting No. B-35 (2013-12-12)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20131212/-1/13666), but OurCommons thinks [#34A is on 2013-12-12](http://www.ourcommons.ca/DocumentViewer/en/41-2/house/sitting-34A/journals) and #35B doesn't exist.
          * ParlVU speaks of [HoC Sitting No. C-35 (2013-12-13)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20131213/-1/13667), but OurCommons thinks no session exists on this date and #35C doesn't exist.
          * ParlVU speaks of [HoC Sitting No. A-50 (2010-05-27)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20100527/-1/18261), but OurCommons thinks [#50 is on 2010-05-27](http://www.ourcommons.ca/DocumentViewer/en/40-3/house/sitting-50/order-notice) and #50A doesn't exist.
          * ParlVU speaks of [HoC Sitting No. A-98 (2008-05-26)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20080526/-1/24242), but OurCommons thinks [#98 is on 2008-05-26](http://www.ourcommons.ca/DocumentViewer/en/39-2/house/sitting-98/order-notice) and #98A doesn't exist.
          * ParlVU speaks of [HoC Sitting No. 118 (2008-09-15)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20080915/-1/24258), but OurCommons thinks no session exists on this date and #118 doesn't exist.
          * ParlVU speaks of [HoC Sitting No. 119 (2008-09-16)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20080916/-1/24259), but OurCommons thinks no session exists on this date and #119 doesn't exist.
          * ParlVU speaks of [HoC Sitting No. 120 (2008-09-17)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20080917/-1/24260), but OurCommons thinks no session exists on this date and #120 doesn't exist.
          * ParlVU speaks of [HoC Sitting No. A-13 (2008-12-04)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20081204/-1/18081), but OurCommons thinks [#13 is on 2008-12-04](http://www.ourcommons.ca/DocumentViewer/en/40-1/house/sitting-13/order-notice) and #13A doesn't exist.
          * ParlVU speaks of [HoC Sitting No. 15 (2008-12-08)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20081208/-1/18079), but OurCommons thinks no session exists on this date and [#15 is on 2009-02-13](http://www.ourcommons.ca/DocumentViewer/en/40-2/house/sitting-15/order-notice).
          * ParlVU speaks of [HoC Sitting No. A-36 (2007-12-12)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20071212/-1/24179), but OurCommons thinks [#36 is on 2007-12-12](http://www.ourcommons.ca/DocumentViewer/en/39-2/house/sitting-36/order-notice) and #36A doesn't exist.
          * ParlVU speaks of [HoC Sitting No. 888 (2006-09-22)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20060922/-1/24055), but OurCommons thinks [#51 is on 2006-09-22](http://www.ourcommons.ca/DocumentViewer/en/39-1/house/sitting-51/order-notice) and #888 doesn't exist.
    """
    CATEGORY_AUDIO_ONLY = 1
    CATEGORY_TELEVISED = 2
    CATEGORY_IN_CAMERA = 2
    CATEGORY_NO_BROADCAST = 3
    CATEGORY_TRAVEL = 4
    STATUS_ADJOURNED = 1
    STATUS_CANCELLED = 2
    STATUS_NOT_STARTED = 3

    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    actual_start = models.DateTimeField(null=True)
    actual_end = models.DateTimeField(null=True)
    location = json.JSONField()
    category = models.PositiveSmallIntegerField(choices=(
        (CATEGORY_AUDIO_ONLY, "Audio only"),
        (CATEGORY_TELEVISED, "Televised"),
        (CATEGORY_IN_CAMERA, "In Camera"),
        (CATEGORY_NO_BROADCAST, "No Broadcast"),
        (CATEGORY_TRAVEL, "Travel"),
    ))
    status = models.PositiveSmallIntegerField(choices=(
        (STATUS_ADJOURNED, "Adjourned"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_NOT_STARTED, "Not Started"),
    ))

    class Meta:
        ordering = ("slug", )


class Sitting(LinksMixin, models.Model):
    """
        ## Data sources

        * [House of Commons' House Publications (35th Parliament onwards)](http://www.ourcommons.ca/documentviewer/en/house/latest-sitting)
    """
    slug = models.SlugField(max_length=200, primary_key=True)
    number = models.CharField(max_length=5, db_index=True)
    session = models.ForeignKey(parliament_models.Session, related_name="sittings")
    date = models.DateField(unique=True)
    recording = models.ForeignKey(Recording, null=True, blank=True)

    class Meta:
        unique_together = ("session", "number")
        ordering = ("date", )

    def __str__(self):
        return "Sitting {}".format(self.date)


class Committee(NamesMixin, LinksMixin, models.Model):
    """
        ## Data sources

        * [House of Commons' List of Committees (36th Parliament onwards)](http://www.ourcommons.ca/Committees/en/List)
        * [Senate of Canada's List of Committees (35th Parliament onwards)](https://sencanada.ca/en/committees/)
        * [LEGISinfo's Bills (37th Parliament onwards)](http://www.parl.gc.ca/LegisInfo/)
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

        * [LEGISinfo (35th Parliament onwards)](http://www.parl.gc.ca/LegisInfo/)

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

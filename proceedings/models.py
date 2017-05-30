from django.db import models
from django_extensions.db.fields import json
from federal_common.models import NamesMixin, LinksMixin
from parliaments import models as parliament_models


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


class Recording(NamesMixin, LinksMixin, models.Model):
    """
        ## Data sources

        * [ParlVU (39th Parliament onwards)](http://parlvu.parl.gc.ca/)

        ## Notes

        * OurCommons and ParlVU don't always agree. I've identified the following inconsistencies and contacted infonet@parl.gc.ca. I'm currently waiting on a response.
          * (Legitimate discrepency) ParlVU speaks of [HoC Sitting No. 76 (2016-06-17)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20160617/-1/25343), but OurCommons thinks [#75 is on 2016-06-17](http://www.ourcommons.ca/DocumentViewer/en/42-1/house/sitting-75/order-notice) and [#76 is on 2016-09-19](http://www.ourcommons.ca/DocumentViewer/en/42-1/house/sitting-76/order-notice).
          * (Split event) ParlVU speaks of [HoC Sitting No. A-50 (2010-05-27)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20100527/-1/18261), but OurCommons thinks [#50 is on 2010-05-27](http://www.ourcommons.ca/DocumentViewer/en/40-3/house/sitting-50/order-notice) and #50A doesn't exist.
          * (Split event) ParlVU speaks of [HoC Sitting No. A-98 (2008-05-26)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20080526/-1/24242), but OurCommons thinks [#98 is on 2008-05-26](http://www.ourcommons.ca/DocumentViewer/en/39-2/house/sitting-98/order-notice) and #98A doesn't exist.
          * (Split event) ParlVU speaks of [HoC Sitting No. A-13 (2008-12-04)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20081204/-1/18081), but OurCommons thinks [#13 is on 2008-12-04](http://www.ourcommons.ca/DocumentViewer/en/40-1/house/sitting-13/order-notice) and #13A doesn't exist.
          * (Split event) ParlVU speaks of [HoC Sitting No. A-36 (2007-12-12)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20071212/-1/24179), but OurCommons thinks [#36 is on 2007-12-12](http://www.ourcommons.ca/DocumentViewer/en/39-2/house/sitting-36/order-notice) and #36A doesn't exist.
          * (Special sitting with no publications) ParlVU speaks of [HoC Sitting No. 888 (2006-09-22)](http://parlvu.parl.gc.ca/XRender/en/PowerBrowser/PowerBrowserV2/20060922/-1/24055), but OurCommons thinks [#51 is on 2006-09-22](http://www.ourcommons.ca/DocumentViewer/en/39-1/house/sitting-51/order-notice) and #888 doesn't exist.
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
    committee = models.ForeignKey(Committee, null=True, blank=True, related_name="recordings")

    class Meta:
        ordering = ("scheduled_start", "slug")


class Sitting(LinksMixin, models.Model):
    """
        ## Data sources

        * [House of Commons' House Publications (35th Parliament onwards)](http://www.ourcommons.ca/documentviewer/en/house/latest-sitting)

        ## Notes

        * Some House Publication pages don't load properly (e.g. [Parliament 38, Session 1, Sitting 124A](http://www.ourcommons.ca/DocumentViewer/en/38-1/house/sitting-124A/journals)). I've contacted infonet@parl.gc.ca with these issues.
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


class HouseVote(LinksMixin, models.Model):
    """
        ## Data sources

        * [House of Commons' Votes (38th Parliament onwards)](http://www.ourcommons.ca/parliamentarians/en/votes)
    """
    RESULT_NEGATIVED = 1
    RESULT_AGREED_TO = 2
    RESULT_TIE = 3

    slug = models.SlugField(max_length=200, primary_key=True)
    sitting = models.ForeignKey(Sitting, related_name="house_votes")
    number = models.PositiveSmallIntegerField(db_index=True)
    bill = models.ForeignKey(Bill, blank=True, null=True, related_name="house_votes")
    context = json.JSONField()
    result = models.PositiveSmallIntegerField(choices=(
        (RESULT_NEGATIVED, "Negatived"),
        (RESULT_AGREED_TO, "Agreed To"),
        (RESULT_TIE, "Tie"),
    ))

    class Meta:
        ordering = ("sitting__date", "slug")

    def __str__(self):
        return "{}, House Vote {}".format(self.sitting, self.number)


class HouseVoteParticipant(models.Model):
    """
        ## Data sources

        * [House of Commons' Votes (38th Parliament onwards)](http://www.ourcommons.ca/parliamentarians/en/votes)

        ## Notes

        * The records provide MP party affiliation outside of elections, which can be used to track party affiliation changes between elections.
    """
    VOTE_NAY = 1
    VOTE_YEA = 2
    VOTE_PAIRED = 3
    VOTE_ABSTAINED = 4

    house_vote = models.ForeignKey(HouseVote, related_name="house_vote_participants")
    parliamentarian = models.ForeignKey(parliament_models.Parliamentarian, related_name="house_vote_participants")
    party = models.ForeignKey(parliament_models.Party, related_name="house_vote_participants", null=True)
    recorded_vote = models.PositiveSmallIntegerField(choices=(
        (VOTE_NAY, "Nay"),
        (VOTE_YEA, "Yea"),
        (VOTE_PAIRED, "Paired"),
        (VOTE_ABSTAINED, "Abstained"),
    ))

    class Meta:
        unique_together = ("house_vote", "parliamentarian")

    def __str__(self):
        return "{}, {}, {}".format(self.house_vote, self.get_recorded_vote_display())

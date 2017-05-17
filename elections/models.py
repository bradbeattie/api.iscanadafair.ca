from django.db import models
from django.utils.html import format_html
from django_extensions.db.fields.json import JSONField
import hashlib
import os


# Unmodelled data:
# * Hansard http://www.parl.gc.ca/housechamberbusiness/ChamberSittings.aspx


class Party(models.Model):
    """
        ## Data sources

        * Elections Canada lists registered parties and recently deregistered parties: http://www.elections.ca/content.aspx?dir=par&document=index&lang=e&section=pol
        * The Library of Parliament lists registered and a selection of former parties: http://www.lop.parl.gc.ca/parlinfo/Lists/Party.aspx
        * Wikipedia lists registered and historical parties: https://en.wikipedia.org/wiki/List_of_federal_political_parties_in_Canada
    """
    name = models.CharField(max_length=200, unique=True)
    name_variants = JSONField()
    color = models.CharField(max_length=20)
    links = JSONField()
    related = models.ManyToManyField("self", blank=True)

    class Meta:
        ordering = ("name", )
        verbose_name_plural = "parties"

    def __str__(self):
        return "{}".format(self.name)

    def color_swatch(self):
        if self.color:
            return format_html("<div style='background: {}; height: 1em; width: 1em; border: 0.1em solid black'></div>", self.color)


class Parliament(models.Model):
    """
        ## Data sources

        * The Library of Parliament lists all parliaments along with detailed profiles: http://www.lop.parl.gc.ca/parlinfo/Compilations/ElectionsAndRidings/Elections.aspx?Menu=ElectionsRidings-Election
    """
    number = models.PositiveSmallIntegerField(primary_key=True)
    government_party = models.ForeignKey(Party, null=True, related_name="governed_parliaments")
    links = JSONField()
    seats = models.PositiveSmallIntegerField(help_text="Aggregate")

    class Meta:
        ordering = ("number", )

    def __str__(self):
        return "Parliament {}".format(self.number)


class GeneralElection(models.Model):
    """
        ## Data sources

        * The Library of Parliament lists all general elections, their ridings, and their candidates: http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=G
        * Elections Canada provides federally-scoped per-election population data: http://www.elections.ca/content.aspx?section=ele&dir=turn&document=index&lang=e
        * Wikipedia lists all general elections along with party performance summaries: https://en.wikipedia.org/wiki/List_of_Canadian_federal_general_elections
    """
    number = models.PositiveSmallIntegerField(primary_key=True)
    parliament = models.OneToOneField(Parliament, related_name="general_election")
    date_start = models.DateField()
    date_end = models.DateField(null=True)
    population = models.PositiveIntegerField(help_text="Aggregate")
    registered = models.PositiveIntegerField(help_text="Aggregate")
    ballots_total = models.PositiveIntegerField(help_text="Aggregate, includes rejected ballots")
    turnout = models.DecimalField(max_digits=3, decimal_places=3, help_text="Aggregate")
    links = JSONField()
    wiki_info_box = JSONField()

    class Meta:
        ordering = ("date_end", )

    def __str__(self):
        return "General Election {} ({})".format(self.number, self.date_end or self.date_start)


class Province(models.Model):
    """
        ## Data sources

        * The Library of Parliament lists provinces and territories: http://www.lop.parl.gc.ca/parlinfo/compilations/ProvinceTerritory.aspx?Menu=ProvinceTerritory
          * Additionally, profiles list a significant amount of auxilliary data incuding links to provincial assemblies.
    """
    name = models.CharField(max_length=200, unique=True)
    name_variants = JSONField()
    links = JSONField()

    class Meta:
        ordering = ("name", )

    def __str__(self):
        return "{}".format(self.name)


def get_photo_path(instance, filename):
    return os.path.join(
        "photos",
        filename[0:2],
        filename,
    )


class Parliamentarian(models.Model):
    """
        ## Data sources

        * OpenParliament.ca lists active and recent parliamentarians: https://openparliament.ca/politicians/
        * Parliament lists active and rececent parliamentarians: http://www.parl.gc.ca/Parliamentarians/en/members
          * Additionally, profiles list email addresses, websites, committees, and expenditures
        * The Library of Parliament lists election canadidates and in some cases detailed parliamentarian profiles: http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=C
          * Additionally, detailed profiles often are accompanied by a photo.
    """
    name = models.CharField(max_length=200, unique=True)  # Names aren't unique (e.g. David Anderson), but we require the primary name to be unique, suffixed with "(n)" where appropriate
    name_variants = JSONField()
    photo = models.ImageField(upload_to=get_photo_path)
    birthtext = models.CharField(max_length=10, db_index=True, help_text="Exact birth dates for parliamentarians in the 1800s sometimes omitted day or month")
    birthdate = models.DateField(null=True, db_index=True)
    links = JSONField()

    class Meta:
        ordering = ("name", )

    def __str__(self):
        return "{}".format(self.name)


class Riding(models.Model):
    """
        ## Data sources

        * Elections Canada lists current federal electoral districts: http://www.elections.ca/Scripts/vis/SearchProvinces?L=e&PROV=CA&PROVID=99999&QID=-1&PAGEID=20
          * Additionally, profiles list adjacent districts and boundary maps.
        * The Library of Parliament lists ridings since confederation: http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=R
          * Additionally, profiles list historically related ridings and descriptions of boundaries.
        * Parliament lists current constituencies: http://www.parl.gc.ca/Parliamentarians/en/constituencies
          * Additionally, profiles list constituency office addresses, phone numbers, and current MP.
    """
    name = models.CharField(max_length=200, db_index=True)
    name_variants = JSONField()
    province = models.ForeignKey(Province, related_name="ridings")
    links = JSONField()
    related_historically = models.ManyToManyField("self", blank=True)
    related_geographically = models.ManyToManyField("self", blank=True)

    class Meta:
        unique_together = ("name", "province")
        ordering = ("province__name", "name")

    def __str__(self):
        return "{}: {}".format(self.province, self.name)


class ElectionRiding(models.Model):
    """
        ## Data sources

        * Early Canadiana Online has the relevant sessional papers from the 1st through 14th General Election.
        * Elections Canada can upon specific email request send a DVD containing the relevant reports for the 13th through 34th General Election.
        * Elections Canada makes the 35th General Election results available in hard copy: http://www.elections.ca/pub_01.aspx?lang=e (warning: it's physically massive)
        * Elections Canada makes the 36th through 42nd General Election results available for download: http://www.elections.ca/content.aspx?section=ele&dir=pas&document=index&lang=e
        * I've personally made an effort to catalogue the relevant columns I could not otherwise infer from the Library of Parliament's historical records (population, electors on the list, rejected ballots): https://github.com/bradbeattie/canadian-parlimentarty-data/raw/master/riding-populations-electors-and-rejected-ballots.ods
        * The Library of Parliament provides general election and by-election candidate breakdowns: http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=G
    """
    general_election = models.ForeignKey(GeneralElection, related_name="election_ridings", null=True)
    by_election_parliament = models.ForeignKey(Parliament, related_name="by_election_ridings", null=True)

    date = models.DateField(db_index=True)
    riding = models.ForeignKey(Riding, related_name="election_ridings")
    ballots_rejected = models.PositiveIntegerField(null=True)
    registered = models.PositiveIntegerField(null=True)
    population = models.PositiveIntegerField(null=True)
    links = JSONField()

    class Meta:
        index_together = [
            ("general_election", "riding"),
            ("by_election_parliament", "riding"),
        ]
        ordering = ("date", "riding__province__name", "riding__name")

    def __str__(self):
        if self.general_election:
            return "{}, {}".format(self.general_election, self.riding)
        else:
            return "By-Election of {}, {}".format(self.date, self.riding)

    def consistency_check(self):
        assert self.general_election or self.by_election_parliament or not self.pk, "ElectionRidings must reference an election"
        assert not (self.general_election and self.by_election_parliament), "ElectionRidings cannot be for both general and by-elections"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.consistency_check()

    def save(self, *args, **kwargs):
        self.consistency_check()
        return super().save(*args, **kwargs)


class ElectionCandidate(models.Model):
    """
        ## Data sources

        * The Library of Parliament lists election canadidates and in some cases detailed parliamentarian profiles: http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=C
    """
    election_riding = models.ForeignKey(ElectionRiding, related_name="election_candidates")
    name = models.CharField(max_length=200, db_index=True)
    parliamentarian = models.ForeignKey(Parliamentarian, related_name="election_candidates", null=True)
    party = models.ForeignKey(Party, null=True, related_name="election_candidates")
    profession = models.CharField(max_length=200)
    ballots = models.PositiveIntegerField(null=True)
    ballots_percentage = models.DecimalField(max_digits=4, decimal_places=3, help_text="Aggregate", null=True)
    elected = models.BooleanField()
    acclaimed = models.BooleanField()

    class Meta:
        ordering = (
            "election_riding__date",
            "election_riding__riding__province__name",
            "election_riding__riding__name",
            "name",
        )

    def __str__(self):
        return "{}, {}".format(self.election_riding, self.name)


class Session(models.Model):
    """
        ## Data sources

        * The Library of Parliament publishes profiles for each parliament, including details on each session: http://www.lop.parl.gc.ca/parlinfo/Lists/Parliament.aspx
    """
    parliament = models.ForeignKey(Parliament, related_name="sessions")
    number = models.PositiveSmallIntegerField(db_index=True)
    date_start = models.DateField(db_index=True)
    date_end = models.DateField(null=True, db_index=True)
    sittings_house = models.PositiveSmallIntegerField()
    sittings_senate = models.PositiveSmallIntegerField()
    links = JSONField()

    class Meta:
        unique_together = ("parliament", "number")
        ordering = ("parliament__number", "number")

    def __str__(self):
        return "{}, Session {} ({} - {})".format(self.parliament, self.number, self.date_start, self.date_end)


class Committee(models.Model):
    """
        ## Data sources

        * Parliament publishes bills through LEGISinfo, including committee data: http://www.parl.gc.ca/LegisInfo/
    """
    CHAMBER_HOC = 1
    CHAMBER_SEN = 2

    code = models.CharField(max_length=4, unique=True)
    name = models.CharField(max_length=200)
    chamber = models.PositiveSmallIntegerField(choices=(
        (CHAMBER_HOC, "House of Commons"),
        (CHAMBER_SEN, "Senate"),
    ))
    links = JSONField()

    class Meta:
        ordering = ("code", )

    def __str__(self):
        return "{}: {}".format(self.code, self.name)


class Bill(models.Model):
    """
        ## Data sources

        * Parliament lists recent bills at LEGISinfo: http://www.parl.gc.ca/LegisInfo/
    """
    session = models.ForeignKey(Session, related_name="bills")
    code_letter = models.CharField(max_length=1, db_index=True)
    code_number = models.PositiveSmallIntegerField(db_index=True)
    title = models.TextField()
    short_title = models.CharField(max_length=200)
    links = JSONField()
    committees = models.ManyToManyField(Committee, related_name="bills")

    class Meta:
        unique_together = ("session", "code_letter", "code_number")
        ordering = ("session__number", "code_letter", "code_number")

    def __str__(self):
        return "{}, {}-{}".format(self.session, self.code_letter, self.code_number)


class Sitting(models.Model):
    """
        I have no exhaustive list of sittings at the moment. I'd like one!

        ## Data sources

        * Parliament publishes sittings wherein there was a vote (38th parliament onward): http://www.parl.gc.ca/HouseChamberBusiness/ChamberVoteList.aspx?Language=E
    """
    session = models.ForeignKey(Session, related_name="sittings")
    number = models.PositiveSmallIntegerField(db_index=True)
    date = models.DateField(db_index=True)

    class Meta:
        unique_together = ("session", "number")

    def __str__(self):
        return "{}, Sitting {} ({})".format(self.session, self.number, self.date)


class SittingVote(models.Model):
    """
        ## Data sources

        * Parliament publishes votes since the 38th parliament: http://www.parl.gc.ca/housechamberbusiness/ChamberVoteList.aspx
    """
    sitting = models.ForeignKey(Sitting, related_name="sitting_votes")
    number = models.PositiveSmallIntegerField(db_index=True)
    bill = models.ForeignKey(Bill, blank=True, null=True, related_name="sitting_votes")
    context = models.TextField()
    links = JSONField()

    class Meta:
        unique_together = ("sitting", "number")

    def __str__(self):
        return "{}, Vote {}".format(self.sitting, self.number)


class SittingVoteParticipant(models.Model):
    """
        ## Data sources

        * Parliament publishes votes and vote details since the 38th parliament: http://www.parl.gc.ca/housechamberbusiness/ChamberVoteList.aspx
          * Additionally, votes come with party affilliation which is useful in tracking party affiliation when MPs switch between elections.
    """
    VOTE_NAY = 1
    VOTE_YEA = 2
    VOTE_PAIRED = 3
    VOTE_ABSTAINED = 4

    sitting_vote = models.ForeignKey(SittingVote, related_name="sitting_vote_participants")
    parliamentarian = models.ForeignKey(Parliamentarian, related_name="sitting_vote_participants")
    party = models.ForeignKey(Party, related_name="sitting_vote_participants", null=True)
    recorded_vote = models.PositiveSmallIntegerField(choices=(
        (VOTE_NAY, "Nay"),
        (VOTE_YEA, "Yea"),
        (VOTE_PAIRED, "Paired"),
        (VOTE_ABSTAINED, "Abstained"),
    ))

    class Meta:
        unique_together = ("sitting_vote", "parliamentarian")

    def __str__(self):
        return "{}, {}, {}".format(self.sitting_vote, self.parliamentarian, self.get_recorded_vote_display())

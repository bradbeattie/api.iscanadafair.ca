from django.db import models
from federal_common.sources import EN, FR
from parliaments import models as parliament_models
from django_extensions.db.fields import json
import inflect


inflector = inflect.engine()


class GeneralElection(models.Model):
    """
        ## Data sources

        * The Library of Parliament lists all general elections, their ridings, and their candidates: http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=G
        * Elections Canada provides federally-scoped per-election population data: http://www.elections.ca/content.aspx?section=ele&dir=turn&document=index&lang=e
        * Wikipedia lists all general elections along with party performance summaries: https://en.wikipedia.org/wiki/List_of_Canadian_federal_general_elections
    """
    number = models.PositiveSmallIntegerField(primary_key=True)
    parliament = models.OneToOneField(parliament_models.Parliament, related_name="general_election")
    date_fuzz = models.DateField(help_text="TODO: Explain date problems")
    date = models.DateField()
    population = models.PositiveIntegerField(help_text="Aggregate")
    registered = models.PositiveIntegerField(help_text="Aggregate")
    ballots_total = models.PositiveIntegerField(help_text="Aggregate, includes rejected ballots")
    turnout = models.DecimalField(max_digits=3, decimal_places=3, help_text="Aggregate")
    links = json.JSONField()
    wiki_info_box = json.JSONField()

    class Meta:
        ordering = ("date", )

    def __str__(self):
        return self.name(EN)

    def name(self, lang):
        return {
            EN: "{} General Election".format(inflector.ordinal(self.number)),
            FR: "{} élection générale".format(self.number, "re" if self.number == 1 else "e"),
        }[lang]


class ByElection(models.Model):
    """
        ## Data sources

        * The Library of Parliament lists all by-elections, their ridings, and their candidates: http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=B
    """
    parliament = models.ForeignKey(parliament_models.Parliament, related_name="by_elections")
    date = models.DateField()
    links = json.JSONField()

    class Meta:
        ordering = ("date", )

    def name(self, lang):
        return {
            EN: "By-election ({})".format(self.date),
            FR: "Élection partielle ({})".format(self.date),
        }[lang]

    def __str__(self):
        return "By-Election ({})".format(self.date)


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
    by_election = models.ForeignKey(ByElection, related_name="election_ridings", null=True)

    date = models.DateField(db_index=True)
    riding = models.ForeignKey(parliament_models.Riding, related_name="election_ridings")
    ballots_rejected = models.PositiveIntegerField(null=True)
    registered = models.PositiveIntegerField(null=True)
    population = models.PositiveIntegerField(null=True)

    class Meta:
        index_together = [
            ("general_election", "riding"),
            ("by_election", "riding"),
        ]
        ordering = ("date", "riding__slug")

    def __str__(self):
        if self.general_election:
            return "{}, {}".format(self.general_election, self.riding)
        else:
            return "{}, {}".format(self.by_election, self.riding)

    def consistency_check(self):
        assert self.general_election_id or self.by_election_id or not self.pk, "ElectionRidings must reference an election"
        assert not (self.general_election_id and self.by_election_id), "ElectionRidings cannot be for both general and by-elections"

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
    parliamentarian = models.ForeignKey(parliament_models.Parliamentarian, related_name="election_candidates", null=True)
    party = models.ForeignKey(parliament_models.Party, null=True, related_name="election_candidates")
    profession = models.CharField(max_length=200)
    ballots = models.PositiveIntegerField(null=True)
    ballots_percentage = models.DecimalField(max_digits=4, decimal_places=3, help_text="Aggregate", null=True)
    elected = models.BooleanField()
    acclaimed = models.BooleanField()

    class Meta:
        ordering = (
            "election_riding__date",
            "election_riding__riding__slug",
            "name",
        )

    def __str__(self):
        return "{}, {}".format(self.election_riding, self.name)

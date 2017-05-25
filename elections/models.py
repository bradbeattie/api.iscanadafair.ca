from django.db import models
from federal_common.sources import EN, FR
from parliaments import models as parliament_models
from django_extensions.db.fields import json
import inflect


inflector = inflect.engine()


class GeneralElection(models.Model):
    """
        ## Data sources

        * [Library of Parliament's General Elections](http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=G)
        * [Elections Canada's Voter Turnout at Federal Elections and Referendums](http://www.elections.ca/content.aspx?section=ele&dir=turn&document=index&lang=e)
        * [Wikipedia's List of Canadian federal general elections](https://en.wikipedia.org/wiki/List_of_Canadian_federal_general_elections)
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

        * [Library of Parliament's By-Elections](http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=B)
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

        * [Early Canadiana Online's Sessional Papers (1st through 14th Parliament, paywall)](http://eco.canadiana.ca/)
        * [Elections Canada](http://www.elections.ca/)
          * [Raw data (38th through 42nd General Elections)](http://www.elections.ca/content.aspx?section=ele&dir=pas&document=index&lang=e)
          * [HTML data (36th and 37th General Elections)](http://www.elections.ca/content.aspx?section=ele&dir=pas&document=index&lang=e)
          * [Hardy copy (35th General Election, warning: physically massive)](http://www.elections.ca/pub_01.aspx?lang=e)
          * [PDF data (13th through 34th General Elections, by specific request)](https://secure.elections.ca/FeedbackQuestion.aspx?lang=e) *[(Not yet complete)](https://github.com/bradbeattie/canadian-parliamentary-data/issues/14)*
        * [Library of Parliament's History of Federal Ridings](https://lop.parl.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=G)
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

        * [Library of Parliament's Candidates](http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=C)
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

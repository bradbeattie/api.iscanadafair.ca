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

        ## Notes

        * A candidate might run in one election as John Doe, but in the next as Jonny Doe. More frustrating still, a John Doe may run in one election, and a different John Doe in the next election in the same riding. [The Library of Parliament's History of Federal Ridings (HFER)](https://lop.parl.ca/About/Parliament/FederalRidingsHistory/HFER.asp) doesn't uniquely identify candidates and the research involved in doing so is well beyond the scope of this project. As such, only candidates that win are linked with their [parliamentarian](/parliamentarians/) object as per the available data. This means that looking at a parliamentarian, one can't get the list of failed candidacies as I don't have a solid enough source for that. Omitting spotty data seems a safer bet than including it.
        * Historically, a candidate's party affilialtion might be harder to deduce than one might expect. Take the case of [Norman James Macdonald Lockhart](https://lop.parl.ca/parlinfo/Files/Parliamentarian.aspx?Item=8071f7cb-6056-4879-99dc-e913be0cb2ec) who runs in the 19th General Election [as a member of the National Government Party](https://lop.parl.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=Gres&genElection=19&ridProvince=9), yet appears in ParlInfo [as a member of the Conservative Party (1867-1942)](https://lop.parl.ca/parlinfo/Files/Parliament.aspx?Item=09eeff1b-e930-4148-b062-729f06cd6860&Language=E&Section=Elections). Dave Tessier, ParlInfo Coordinator, explains: *A word of caution; the early elections were very difficult to compile and if you research other sources you will indeed find conflicting information at times. We focused on the most authoritative sources at our disposal during the time that this data was assembled, and when we discovered a conflict we simply tried to determine which information was the most reliable. Further, party affiliations in the early years are very difficult if not impossible to determine. Although not always clear, you can assume that HFER shows the "candidate affiliation" and the Parliamentarian file will show the affiliation in the House of Commons. Some of the affiliations for the earlier parliaments where very difficult to confirm.*
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
        return self.name

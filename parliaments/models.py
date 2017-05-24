from django.db import models
from federal_common.models import NamesMixin, LinksMixin
from django.utils.html import format_html
import os


class Party(NamesMixin, LinksMixin, models.Model):
    """
        ## Data sources

        * Elections Canada lists registered parties and recently deregistered parties: http://www.elections.ca/content.aspx?dir=par&document=index&lang=e&section=pol
        * The Library of Parliament lists registered and a selection of former parties: http://www.lop.parl.gc.ca/parlinfo/Lists/Party.aspx
        * Wikipedia lists registered and historical parties: https://en.wikipedia.org/wiki/List_of_federal_political_parties_in_Canada
    """
    color = models.CharField(max_length=20)
    related = models.ManyToManyField("self", blank=True)
    lop_item_code = models.SlugField(db_index=True, null=True)

    class Meta:
        ordering = ("slug", )
        verbose_name_plural = "parties"

    def color_swatch(self):
        if self.color:
            return format_html("<div style='background: {}; height: 1em; width: 1em; border: 0.1em solid black'></div>", self.color)


class Parliament(LinksMixin, models.Model):
    """
        ## Data sources

        * The Library of Parliament lists all parliaments along with detailed profiles: http://www.lop.parl.gc.ca/parlinfo/Compilations/ElectionsAndRidings/Elections.aspx?Menu=ElectionsRidings-Election
    """
    number = models.PositiveSmallIntegerField(primary_key=True)
    government_party = models.ForeignKey(Party, null=True, related_name="governed_parliaments")
    seats = models.PositiveSmallIntegerField(help_text="Aggregate", null=True)

    class Meta:
        ordering = ("number", )

    def __str__(self):
        return "Parliament {}".format(self.number)


class Session(LinksMixin, models.Model):
    """
        ## Data sources

        * The Library of Parliament publishes profiles for each parliament, including details on each session: http://www.lop.parl.gc.ca/parlinfo/Lists/Parliament.aspx
    """
    slug = models.SlugField(max_length=200, primary_key=True)
    parliament = models.ForeignKey(Parliament, related_name="sessions")
    number = models.PositiveSmallIntegerField(db_index=True)
    date_start = models.DateField(db_index=True)
    date_end = models.DateField(null=True, db_index=True)
    sittings_house = models.PositiveSmallIntegerField()
    sittings_senate = models.PositiveSmallIntegerField()

    class Meta:
        unique_together = ("parliament", "number")
        ordering = ("parliament__number", "number")

    def __str__(self):
        return "{}, Session {}".format(self.parliament, self.number)


class Province(NamesMixin, LinksMixin, models.Model):
    """
        ## Data sources

        * The Library of Parliament lists provinces and territories along with supplemental links: http://www.lop.parl.gc.ca/parlinfo/compilations/ProvinceTerritory.aspx?Menu=ProvinceTerritory
    """

    class Meta:
        ordering = ("slug", )


def get_photo_path(instance, filename):
    return os.path.join(
        "photos",
        filename[0:2],
        filename,
    )


class Parliamentarian(NamesMixin, LinksMixin, models.Model):
    """
        ## Data sources

        * OpenParliament.ca lists active and recent parliamentarians: https://openparliament.ca/politicians/
        * Parliament lists active and rececent parliamentarians, along with extensive supplemental data: http://www.parl.gc.ca/Parliamentarians/en/members
        * The Library of Parliament lists election canadidates and in some cases detailed parliamentarian profiles: http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=C
    """
    photo = models.ImageField(upload_to=get_photo_path)
    birthtext = models.CharField(max_length=10, db_index=True, help_text="Exact birth dates for parliamentarians in the 1800s sometimes omitted day or month")
    birthdate = models.DateField(null=True, db_index=True)
    lop_item_code = models.SlugField(db_index=True, unique=True)

    class Meta:
        ordering = ("slug", )


class Riding(NamesMixin, LinksMixin, models.Model):
    """
        ## Data sources

        * Elections Canada lists current federal electoral districts: http://www.elections.ca/Scripts/vis/SearchProvinces?L=e&PROV=CA&PROVID=99999&QID=-1&PAGEID=20
        * The Library of Parliament lists ridings since confederation: http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=R
        * Parliament lists current constituencies: http://www.parl.gc.ca/Parliamentarians/en/constituencies

        ## Filtering examples

        * [Ridings in British Columbia](?slug__startswith=british-columbia-)
        * [Ridings named like Vancouver](?names__icontains=vancouver)
    """
    province = models.ForeignKey(Province, related_name="ridings")
    related_historically = models.ManyToManyField("self", blank=True)
    related_geographically = models.ManyToManyField("self", blank=True)
    electoral_district_number = models.PositiveIntegerField(null=True, db_index=True)

    class Meta:
        ordering = ("slug", )

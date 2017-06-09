from django.db import models
from django.utils.html import format_html
from django_extensions.db.fields import json
from federal_common.models import NamesMixin, LinksMixin
import os


class Party(NamesMixin, LinksMixin, models.Model):
    """
        ## Data sources

        * [Elections Canada's Registered Political Parties and Parties Eligible for Registration](http://www.elections.ca/content.aspx?dir=par&document=index&lang=e&section=pol)
        * [Library of Parliament's Party Profiles](http://www.lop.parl.gc.ca/parlinfo/Lists/Party.aspx)
        * [Wikipedia's List of federal political parties in Canada](https://en.wikipedia.org/wiki/List_of_federal_political_parties_in_Canada)
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

        * [Library of Parliament's Parliament Profiles](http://www.lop.parl.gc.ca/parlinfo/Compilations/ElectionsAndRidings/Elections.aspx?Menu=ElectionsRidings-Election)
        * [Wikipedia's List of Canadian federal parliaments](https://en.wikipedia.org/wiki/List_of_Canadian_federal_parliaments)
    """
    number = models.PositiveSmallIntegerField(primary_key=True)
    government_party = models.ForeignKey(Party, null=True, related_name="governed_parliaments", db_index=True)
    seats = models.PositiveSmallIntegerField(help_text="Aggregate", null=True, db_index=True)

    class Meta:
        ordering = ("number", )

    def __str__(self):
        return "Parliament {}".format(self.number)


class Session(LinksMixin, models.Model):
    """
        ## Data sources

        * [Library of Parliament's Parliament Profiles](http://www.lop.parl.gc.ca/parlinfo/Lists/Parliament.aspx)
    """
    slug = models.SlugField(max_length=200, primary_key=True)
    parliament = models.ForeignKey(Parliament, related_name="sessions", db_index=True)
    number = models.PositiveSmallIntegerField(db_index=True)
    date_start = models.DateField(db_index=True)
    date_end = models.DateField(null=True, db_index=True)
    sittings_house = models.PositiveSmallIntegerField(db_index=True)
    sittings_senate = models.PositiveSmallIntegerField(db_index=True)

    class Meta:
        unique_together = ("parliament", "number")
        ordering = ("parliament__number", "number")

    def __str__(self):
        return self.slug


class Province(NamesMixin, LinksMixin, models.Model):
    """
        ## Data sources

        * [Library of Parliament's Provinces and Territories](http://www.lop.parl.gc.ca/parlinfo/compilations/ProvinceTerritory.aspx?Menu=ProvinceTerritory)
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

        * [OpenParliament.ca (1994 onwards)](https://openparliament.ca/politicians/)
        * [House of Commons' Members of Parliament](http://www.parl.gc.ca/Parliamentarians/en/members)
        * [Library of Parliament's History of Federal Ridings](http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=C)
    """
    photo = models.ImageField(upload_to=get_photo_path)
    birthtext = models.CharField(max_length=10, db_index=True, help_text="Exact birth dates for parliamentarians in the 1800s sometimes omitted day or month")
    birthdate = models.DateField(null=True, db_index=True)
    lop_item_code = models.SlugField(db_index=True, unique=True)
    constituency_offices = json.JSONField()
    hill_phone = models.CharField(max_length=20, db_index=True)
    hill_fax = models.CharField(max_length=20, db_index=True)

    LANG_EN = 1
    LANG_FR = 2
    LANG_BOTH = 3
    preferred_language = models.PositiveSmallIntegerField(choices=(
        (LANG_EN, "English"),
        (LANG_FR, "Français"),
        (LANG_BOTH, "English / Français"),
    ), null=True, db_index=True)

    class Meta:
        ordering = ("slug", )


class Riding(NamesMixin, LinksMixin, models.Model):
    """
        ## Data sources

        * [Elections Canada's Electoral District Profiles (current ridings only)](http://www.elections.ca/Scripts/vis/SearchProvinces?L=e&PROV=CA&PROVID=99999&QID=-1&PAGEID=20)
        * [House of Common's Current Constituencies (current ridings only)](http://www.parl.gc.ca/Parliamentarians/en/constituencies)
        * [Library of Parliament's History of Federal Ridings](http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=R)

        ## Notes

        * Some riding profile pages, from which we obtain historically related ridings, don't load properly (e.g. [Western Arctic](http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Include=Y&Language=F&Search=Det&rid=808). I've contacted info@parl.gc.ca regarding these issues.

        ## Filtering examples

        * [Ridings in British Columbia](?slug__startswith=british-columbia-)
        * [Ridings named like Vancouver](?names__icontains=vancouver)
    """
    province = models.ForeignKey(Province, related_name="ridings")
    related_historically = models.ManyToManyField("self", blank=True)
    related_geographically = models.ManyToManyField("self", blank=True)
    electoral_district_number = models.PositiveIntegerField(null=True, db_index=True)
    major_census_subdivisions = json.JSONField()
    area_km2 = models.PositiveIntegerField(null=True, db_index=True)
    postal_code_fsas = json.JSONField()
    current_parliamentarian = models.OneToOneField(Parliamentarian, null=True, related_name="riding", db_index=True)

    class Meta:
        ordering = ("slug", )

from bs4 import BeautifulSoup
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from elections import get_by_name_variant
from elections import models
from elections.get_by_name_variant import SkippedObject
from elections.utils import fetch_url
import logging
import re


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        logger.info("Augment with Library of Parliament")
        self.augment_ridings_lop()
        self.augment_parties_lop()
        self.augment_provinces_lop()

    @transaction.atomic
    def augment_parties_lop(self):
        logger.info("Augmenting parties: Library of Parliament")
        lop_soup = BeautifulSoup(fetch_url(
            "http://www.lop.parl.gc.ca/parlinfo/Lists/Party.aspx",
            force_load=not settings.DEBUG,
        ), "html.parser")
        for a in lop_soup.select("td > a"):
            if "_lnkParty_" in a.attrs.get("id", ""):
                try:
                    party = get_by_name_variant.get_party(name=a.text.strip(), search_name_source="Library of Parliament, Political Parties")
                    party.links["Library of Parliament"] = "http://www.lop.parl.gc.ca/parlinfo/Lists/{}&Section=ALL".format(re.sub("&MenuID=.*", "", a.attrs["href"]))
                    party.save()
                except SkippedObject:
                    pass

    @transaction.atomic
    def augment_provinces_lop(self):
        lop_soup = BeautifulSoup(fetch_url(
            "http://www.lop.parl.gc.ca/parlinfo/compilations/ProvinceTerritory.aspx?Menu=ProvinceTerritory",
            force_load=not settings.DEBUG,
        ), "html.parser")
        for link in lop_soup.select("#ctl00_pnlContent a"):
            if link.attrs.get("id", "").startswith("ctl00_cphContent_repProvinces_"):
                province = models.Province.objects.get(name=link.text.strip())
                province.links["Library of Parliament"] = "http://www.lop.parl.gc.ca/parlinfo/{}&Section=ALL".format(link.attrs["href"][3:])
                province.save()
                self.augment_province_lop(province)

    def augment_province_lop(self, province):
        lop_soup = BeautifulSoup(fetch_url(province.links["Library of Parliament"], force_load=not settings.DEBUG), "html.parser")
        province.links.update(dict(
            (link.text.strip(), link.attrs["href"])
            for link in lop_soup.select("#ctl00_cphContent_dataLinks a")
        ))
        province.save()

    @transaction.atomic
    def augment_ridings_lop(self):
        for riding in models.Riding.objects.all():
            for source, link in riding.links.items():
                if source.startswith("Library of Parliament, "):
                    riding_soup = BeautifulSoup(fetch_url(link), "html.parser")
                    for tag_id in ("#previous", "#became"):
                        related_ridings = riding_soup.select(tag_id)
                        if related_ridings:
                            for related in related_ridings[0].parent.select("a"):
                                try:
                                    match = re.search(r"^(?P<name>.*) \((?P<province>.*)\)\((?P<daterange>.*)\)", related.text).groupdict()
                                    if match["daterange"] != " - ":
                                        riding.related_historically.add(get_by_name_variant.get_riding(
                                            province=models.Province.objects.get(name=match["province"]),
                                            name=match["name"],
                                            search_name_source="Library of Parliament, Related",
                                        ))
                                except SkippedObject:
                                    pass

from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from elections import get_by_name_variant
from elections.get_by_name_variant import SkippedObject
from elections.utils import fetch_url
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        logger.info("Augment with Elections Canada")
        self.augment_parties_ec()
        self.augment_ridings_ec()

    @transaction.atomic
    def augment_parties_ec(self):
        logger.info("Augmenting parties: Elections Canada")
        ec_soup = BeautifulSoup(fetch_url(
            "http://www.elections.ca/content.aspx?dir=par&document=index&lang=e&section=pol",
            force_load=not settings.DEBUG,
        ), "html.parser")
        for h3 in ec_soup.select("h3.partytitle"):
            try:
                party = get_by_name_variant.get_party(name=h3.text.strip(), search_name_source="Elections Canada")
                party.links["Elections Canada Summary"] = "http://www.elections.ca/content.aspx?dir=par&document=index&lang=e&section=pol#{}".format(h3.attrs["id"])
                if h3.a:
                    party.links["Elections Canada Referral"] = h3.a.attrs["href"]
                party.save()
            except SkippedObject:
                pass

    @transaction.atomic
    def augment_ridings_ec(self):
        ec_soup = BeautifulSoup(fetch_url(
            "http://www.elections.ca/Scripts/vis/SearchProvinces?L=e&PROV=CA&PROVID=99999&QID=-1&PAGEID=20",
            force_load=not settings.DEBUG
        ), "html.parser")
        for link in ec_soup.select("table a"):
            riding = get_by_name_variant.get_riding(
                election_ridings__date__year__gt=2010,
                name=link.text,
                search_name_source="Elections Canada, Profile",
            )
            ec_id = parse_qs(urlparse(
                "http://www.elections.ca{}".format(link.attrs["href"])
            ).query)["ED"][0]
            riding.links["Elections Canada, FAQ"] = "http://www.elections.ca/Scripts/vis/EDInfo?L=e&ED={}&EV=99".format(ec_id)
            riding.links["Elections Canada, Map"] = "http://www.elections.ca/Scripts/vis/maps/maps338/{}.gif".format(ec_id)
            riding.links["Elections Canada, Profile"] = "http://www.elections.ca/Scripts/vis/Profile?L=e&ED={}".format(ec_id)
            riding.save()
            self.augment_riding_ec(riding)

    def augment_riding_ec(self, riding):
        ec_soup = BeautifulSoup(fetch_url(
            riding.links["Elections Canada, Profile"],
            force_load=not settings.DEBUG,
            allow_redirects=True,
        ), "html.parser")
        for h2 in ec_soup.select("h2.legend"):
            if h2.text == "Adjacent electoral districts":
                for link in h2.findNext("div").select("a"):
                    riding.related_geographically.add(get_by_name_variant.get_riding(
                        election_ridings__date__year__gt=2010,
                        name=link.text,
                        search_name_source="Elections Canada, Profile",
                    ))

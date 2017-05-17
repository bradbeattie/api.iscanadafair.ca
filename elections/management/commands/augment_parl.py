from bs4 import BeautifulSoup
from django.db.models import Q
from urllib.parse import urlparse, parse_qs
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from elections import models
from elections import get_by_name_variant
from elections.utils import fetch_url, one_or_none
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        logger.info("Augment with Parliament")
        self.augment_parliamentarians_parl()
        self.augment_ridings_parl()

    @transaction.atomic
    def augment_parliamentarians_parl(self):
        search_name_source = "Parliament, Members"
        fetched = set()
        for parl_link in BeautifulSoup(fetch_url(
            "http://www.parl.gc.ca/Parliamentarians/en/members",
            force_load=not settings.DEBUG
        ), "html.parser").select(".refinement a"):
            if "parliament=" in parl_link.attrs["href"]:
                parl_url = "http://www.parl.gc.ca{}&view=ListAll".format(parl_link.attrs["href"])
                parliament = models.Parliament.objects.get(number=parse_qs(urlparse(parl_url).query)["parliament"][0])
                for mp_row in BeautifulSoup(fetch_url(
                    parl_url,
                    force_load=not settings.DEBUG
                ), "html.parser").select(".content-primary > table > tbody > tr"):
                    mp_url = "http://www.parl.gc.ca{}".format(mp_row.select(".personName a")[0].attrs["href"])
                    if mp_url not in fetched:
                        fetched.add(mp_url)
                        mp_soup = BeautifulSoup(fetch_url(
                            mp_url,
                            force_load=not settings.DEBUG
                        ), "html.parser")
                        province = get_by_name_variant.get_province(
                            name=mp_row.select(".province")[0].text,
                            search_name_source=search_name_source,
                        )
                        parliamentarian = get_by_name_variant.get_parliamentarian(
                            Q(election_candidates__election_riding__general_election__parliament=parliament) | Q(election_candidates__election_riding__by_election_parliament=parliament),
                            election_candidates__election_riding__riding__province=province,
                            name=mp_soup.select("h2")[0].text,
                            search_name_source=search_name_source,
                        )
                        # Disabled as parl.gc.ca often uses the wrong name
                        #riding = parliamentarian.election_candidates.get(
                        #    Q(elected=True) | Q(acclaimed=True),
                        #    Q(election_riding__general_election__parliament=parliament) | Q(election_riding__by_election_parliament=parliament),
                        #).election_riding.riding
                        #riding_name = mp_row.select(".constituency")[0].text
                        #if riding_name not in riding.name_variants.values():
                        #    riding.name_variants[search_name_source] = riding_name
                        #    riding.save()
                        parliamentarian.links[search_name_source] = mp_url
                        email = one_or_none(mp_soup.select(".profile.header a[href^=mailto:]"))
                        if email:
                            parliamentarian.links["Email"] = email.attrs["href"][7:]
                        parliamentarian.save()

    @transaction.atomic
    def augment_ridings_parl(self):
        search_name_source = "Parliament, Constituencies"
        for row in BeautifulSoup(fetch_url(
            "http://www.parl.gc.ca/Parliamentarians/en/constituencies",
            force_load=not settings.DEBUG
        ), "html.parser").select(".content-primary > table > tbody > tr"):
            riding_name = row.select("td")[0].text.strip()
            riding_url = "http://www.parl.gc.ca{}".format(row.select(".constituency a")[0].attrs["href"])
            province = get_by_name_variant.get_province(
                name=row.select("td")[1].text.strip(),
                search_name_source=search_name_source,
            )
            riding = get_by_name_variant.get_riding(
                name=riding_name,
                province=province,
                search_name_source=search_name_source,
            )
            riding.links[search_name_source] = riding_url
            riding.save()

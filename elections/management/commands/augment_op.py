from bs4 import BeautifulSoup
from datetime import date
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from elections import get_by_name_variant
from elections.utils import fetch_url
from elections.get_by_name_variant import SkippedObject
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        logger.info("Augment with OpenParliament.ca")
        for url in (
            "https://openparliament.ca/politicians/former/",
            "https://openparliament.ca/politicians/",
        ):
            op_soup = BeautifulSoup(fetch_url(url, force_load=not settings.DEBUG), "html.parser")
            for row in op_soup.select(".content > .row"):
                columns = row.find_all("div", recursive=False)
                if len(columns) == 2 and columns[0].find("h2") and columns[1].find("a"):
                    province = get_by_name_variant.get_province(
                        name=columns[0].find("h2").text,
                        search_name_source="OpenParliament.ca",
                    )
                    for link in columns[1].select("a[href^=/politicians/]"):
                        if link.attrs["href"] not in ("/politicians/", "/politicians/former/"):
                            try:
                                parliamentarian = get_by_name_variant.get_parliamentarian(
                                    name=link.text,
                                    search_name_source="OpenParliament.ca",
                                    election_candidates__election_riding__riding__province=province,
                                    election_candidates__election_riding__date__gt=date(1990, 1, 1),
                                )
                                parliamentarian.links["OpenParliament.ca"] = "https://openparliament.ca/{}".format(link.attrs["href"])
                                parliamentarian.save()
                            except SkippedObject:
                                pass

from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak, REVERSE_ORDINAL
from parliaments import models
from tqdm import tqdm
from urllib.parse import urljoin
import inflect
import logging


logger = logging.getLogger(__name__)
inflector = inflect.engine()


class Command(BaseCommand):

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)
        self.fetch_parliaments()

    def fetch_parliaments(self):
        url = "http://www.lop.parl.gc.ca/parlinfo/Lists/Parliament.aspx"
        for link in tqdm(
            BeautifulSoup(
                fetch_url(url),
                "html.parser",
            ).select("#ctl00_cphContent_ctl00_grdParliamentList td > a"),
            desc="Fetch Parliaments, LoP",
            unit="parliament",
        ):
            parliament, created = models.Parliament.objects.get_or_create(
                number=int(REVERSE_ORDINAL.sub(r"\1", link.text)),
            )
            if created or parliament.number >= 42:
                url = url_tweak(
                    urljoin(url, link.attrs["href"]),
                    remove=("MenuID", "MenuQuery"),
                    update={"Section": "All"},
                )
                parliament.links = {
                    EN: {sources.NAME_WIKI[EN]: "https://en.wikipedia.org/wiki/{}_Canadian_Parliament".format(inflector.ordinal(parliament.number))},
                    FR: {sources.NAME_WIKI[FR]: "https://fr.wikipedia.org/wiki/{}{}_législature_du_Canada".format(parliament.number, "re" if parliament.number == 1 else "e")},
                }
                for lang in (EN, FR):
                    parliament.links[lang][sources.NAME_LOP_PARLIAMENT[lang]] = url_tweak(url, update={"Language": sources.LANG_LOP[lang]})
                    if parliament.number <= 35:
                        parliament.links[lang][sources.NAME_CANADIANA[lang]] = "http://parl.canadiana.ca/search?usrlang={}&lang={}&identifier=P{}".format(
                            sources.LANG_CANADIANA_UI[lang],
                            sources.LANG_CANADIANA_CONTENT[lang],
                            parliament.number,
                        )
                parliament.seats = int(BeautifulSoup(
                    fetch_url(parliament.links[EN][sources.NAME_LOP_PARLIAMENT[EN]], use_cache=True),
                    "html.parser",
                ).select("#ctl00_cphContent_ctl06_pnlSectionPartyStandingsContent .GridRows")[0].contents[-1].text)
                parliament.save()

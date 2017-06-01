from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak
from parliaments import models
from tqdm import tqdm
from urllib.parse import parse_qs, urlparse
import logging
import re


logger = logging.getLogger(__name__)
CITIES = re.compile(r"^(Major census subdivisions|Principales subdivisions de recensement)")
AREA = re.compile(r"^(Area|Superficie)$")


class Command(BaseCommand):

    cached_ridings = {}

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)
        self.augment_ridings_ec()

    def augment_ridings_ec(self):
        for row in tqdm(BeautifulSoup(fetch_url(url_tweak(
            "http://www.elections.ca/Scripts/vis/SearchProvinces?PROV=CA&PROVID=99999&QID=-1&PAGEID=20",
            update={"L": sources.LANG_EC[EN]}
        )), "html.parser").select("table tr")):
            cells = row.find_all("td", recursive=False)
            if cells:
                riding = models.Riding.objects.get(slug=slugify("{} {}".format(
                    cells[1].text,
                    cells[0].text,
                )))
                riding.electoral_district_number = parse_qs(urlparse(cells[0].a.attrs["href"]).query)["ED"][0]
                self.cached_ridings[riding.electoral_district_number] = riding
                riding.save()

        for riding in tqdm(
            models.Riding.objects.filter(electoral_district_number__isnull=False),
            desc="Augment Ridings, Elections Canada",
            unit="riding",
        ):
            self.augment_riding_ec(riding)

    def augment_riding_ec(self, riding):
        for lang in (EN, FR):
            riding.links[lang][sources.NAME_EC_FAQ[lang]] = "http://www.elections.ca/Scripts/vis/EDInfo?L={}&ED={}&EV=99".format(sources.LANG_EC[lang], riding.electoral_district_number)
            riding.links[lang][sources.NAME_EC_MAP[lang]] = "http://www.elections.ca/Scripts/vis/maps/maps338/{}.gif".format(riding.electoral_district_number)
            riding.links[lang][sources.NAME_EC_PROFILE[lang]] = "http://www.elections.ca/Scripts/vis/Profile?L={}&ED={}".format(sources.LANG_EC[lang], riding.electoral_district_number)
            soup = BeautifulSoup(fetch_url(
                riding.links[lang][sources.NAME_EC_PROFILE[lang]],
                allow_redirects=True,
            ), "html.parser")
            riding.names[lang][sources.NAME_EC[lang]] = soup.select("h3.HeaderInfo1")[0].text
            riding.major_census_subdivisions = list(filter(None, map(
                lambda city: city.strip().rstrip("*"),
                soup.find("h2", text=CITIES).find_next_sibling("p").text.splitlines(),
            )))
            riding.area_km2 = int(sources.WHITESPACE.sub("", soup.find("h2", text=AREA).find_next_sibling("p").text.strip()).replace("km2", "").replace(",", ""))
        riding.save()

        for link in soup.select("ul.toc a"):
            riding.related_geographically.add(self.cached_ridings[
                parse_qs(urlparse(link.attrs["href"]).query)["ED"][0]
            ])

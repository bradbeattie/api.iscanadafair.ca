from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak
from parliaments import models
from tqdm import tqdm
from urllib.parse import urljoin
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    ROOT_URL = "https://lop.parl.ca/ParlInfo/Compilations/ProvinceTerritory.aspx"

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)
        self.fetch_provinces()

    def fetch_provinces(self):
        url = url_tweak(self.ROOT_URL, update={"Language": sources.LANG_LOP[EN]})
        for link in tqdm(
            BeautifulSoup(
                fetch_url(url),
                "html.parser",
            ).select("#ctl00_pnlContent a"),
            desc="Fetch Provinces, LoP (EN)",
            unit="province",
        ):
            if link.attrs.get("id", "").startswith("ctl00_cphContent_repProvinces_"):
                province, created = models.Province.objects.get_or_create(slug=slugify(link.text.strip()))
                url_en = url_tweak(
                    urljoin(url, link.attrs["href"]),
                    remove=("MenuID", "MenuQuery"),
                    update={"Section": "All"},
                )
                self.augment_province(province, EN, url_en)

        url = url_tweak(self.ROOT_URL, update={"Language": FR})
        for link in tqdm(
            BeautifulSoup(
                fetch_url(url),
                "html.parser",
            ).select("#ctl00_pnlContent a"),
            desc="Fetch Provinces, LoP (FR)",
            unit="province",
        ):
            if link.attrs.get("id", "").startswith("ctl00_cphContent_repProvinces_"):
                url_fr = url_tweak(
                    urljoin(url, link.attrs["href"]),
                    remove=("MenuID", "MenuQuery"),
                    update={"Section": "All"},
                )
                province = models.Province.objects.get(links__contains=url_tweak(
                    url_fr,
                    update={"Language": sources.LANG_LOP[EN]},
                ))
                self.augment_province(province, FR, url_fr)

    def augment_province(self, province, lang, url):
        soup = BeautifulSoup(
            fetch_url(url),
            "html.parser",
        )
        province.links[lang][sources.NAME_LOP_PROVINCE[lang]] = url
        province.names[lang][sources.NAME_LOP_PROVINCE[lang]] = soup.select("#ctl00_cphContent_lblTitle")[0].text
        province.links[lang][sources.NAME_WIKI[lang]] = "https://{}.wikipedia.org/wiki/{}".format(
            sources.LANG_WIKI[lang],
            province.names[lang][sources.NAME_LOP_PROVINCE[lang]].replace(" ", "_"),
        )
        province.links[lang].update(dict(
            (sources.AVAILABILITY_WARNINGS.sub("", link.text.strip()), link.attrs["href"])
            for link in soup.select("#ctl00_cphContent_dataLinks a")
        ))
        province.save()

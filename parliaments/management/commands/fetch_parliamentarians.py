from bs4 import BeautifulSoup
from collections import defaultdict
from django.conf import settings
from django.core.files.base import ContentFile
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
import os
import requests


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    cache_provinces = {}
    cache_parliamentarians = defaultdict(dict)

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        for parliament in tqdm(
            models.Parliament.objects.all(),
            desc="Fetch Parliamentarians, LoP (lists)",
            unit="parliaments",
        ):
            self.fetch_parliamentarians(parliament)
        for slug, urls in tqdm(
            self.cache_parliamentarians.items(),
            desc="Fetch Parliamentarians, LoP (creating)",
            unit="name",
        ):
            for index, (url, name) in enumerate(urls.items()):
                self.fetch_parliamentarian(slug if len(urls) == 1 else "{}-{}".format(slug, index + 1), name, url)

    def fetch_parliamentarians(self, parliament):
        logger.debug("Fetch parliamentarians, {}".format(parliament))
        url = parliament.links[EN][sources.NAME_LOP_PARLIAMENT[EN]]
        for link in tqdm(
            BeautifulSoup(fetch_url(url), "html.parser").select("a[href^=Parliamentarian]"),
            desc=str(parliament),
            unit="parliamentarian",
        ):
            # We slugify the parliamentarian's name to disambiguate
            # names like "Marcel Masse" and "Marcel Massé"
            self.cache_parliamentarians[slugify(link.text)][url_tweak(
                urljoin(url, link.attrs["href"]),
                update={
                    "MoreInfo": "True",
                    "Section": "All",
                },
            )] = link.text

    @transaction.atomic
    def fetch_parliamentarian(self, slug, name, lang_naive_url):
        parliamentarian, created = models.Parliamentarian.objects.get_or_create(slug=slug)
        if not created:
            return

        for lang in (EN, FR):
            parliamentarian.names[lang][sources.NAME_LOP_PARLIAMENT[lang]] = name
            url = url_tweak(lang_naive_url, update={"Language": sources.LANG_LOP[lang]})
            parliamentarian.links[lang][sources.NAME_LOP_PARLIAMENTARIAN[lang]] = url
            soup = BeautifulSoup(fetch_url(url), "html.parser")
            parliamentarian.names[lang][sources.NAME_LOP_PARLIAMENTARIAN[lang]] = sources.WHITESPACE.sub(" ", soup.select("#ctl00_cphContent_lblTitle")[0].text)
            for link in soup.select("#ctl00_cphContent_dataLinks a"):
                parliamentarian.links[lang][sources.AVAILABILITY_WARNINGS.sub("", link.text.strip())] = link.attrs["href"]
        try:
            parliamentarian.lop_item_code = sources.LOP_CODE.search(url).group().lower()
            parliamentarian.birthdate = soup.select("#ctl00_cphContent_DateOfBirthData")[0].text.strip().replace(".", "-")
        except:
            pass

        # Download the parliamentarian's photo if they have one
        photo_url = urljoin(url, soup.select("#ctl00_cphContent_imgParliamentarianPicture")[0].attrs["src"])
        code = sources.LOP_CODE.search(photo_url).group().lower()
        if code != "00000000-0000-0000-0000-000000000000":
            filename = "{}.jpg".format(code)
            filepath = parliamentarian.photo.field.upload_to(None, filename)
            if os.path.exists(os.path.join(settings.MEDIA_ROOT, filepath)):
                parliamentarian.photo = filepath
            else:
                parliamentarian.photo.save(filename, ContentFile(requests.get(photo_url).content))

        parliamentarian.save()

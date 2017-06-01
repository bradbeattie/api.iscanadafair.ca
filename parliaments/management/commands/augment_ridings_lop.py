from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, get_cached_dict, get_cached_obj, url_tweak, FetchSuppressed, FetchFailure
from parliaments import models
from tqdm import tqdm
from urllib.parse import urljoin
import logging
import re


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)
        self.augment_ridings_lop()

    def augment_ridings_lop(self):
        self.cached_ridings = get_cached_dict(models.Riding.objects.all())
        self.cached_provinces = get_cached_dict(models.Province.objects.all())
        for riding in tqdm(
            models.Riding.objects.all(),
            desc="Augment Ridings, LoP",
            unit="riding",
        ):
            self.augment_riding(riding)

    @transaction.atomic
    def augment_riding(self, riding):
        try:
            for lang in (FR, EN):
                url = riding.links[lang][sources.NAME_LOP_RIDING_HISTORY[lang]]
                soup = BeautifulSoup(fetch_url(url), "html.parser")
                riding.names[lang][sources.NAME_LOP_RIDING_HISTORY[lang]] = soup.select("h4")[0].text.split(", ")[0]
        except (KeyError, FetchFailure, FetchSuppressed) as e:
            logger.exception(e)
            return

        riding.save()
        for tag_id in ("#previous", "#became"):
            related_ridings = soup.select(tag_id)
            if related_ridings:
                for link in related_ridings[0].parent.select("a"):
                    match = re.search(r"^(?P<name>.*) \((?P<province>.*)\)\((?P<daterange>.*)\)", link.text).groupdict()
                    riding_slug = slugify("{province}-{name}".format(**match))
                    try:
                        related_riding = get_cached_obj(self.cached_ridings, riding_slug)
                    except AssertionError:
                        province = get_cached_obj(self.cached_provinces, match["province"])
                        related_riding, created = models.Riding.objects.get_or_create(slug=riding_slug, province=province)
                        logger.debug("Auxilliary riding detected: {}".format(riding_slug))
                    for lang in (EN, FR):
                        if sources.NAME_LOP_RIDING_HISTORY[lang] not in related_riding.links[lang]:
                            related_riding.links[lang][sources.NAME_LOP_RIDING_HISTORY[lang]] = url_tweak(
                                urljoin(url, link.attrs["href"]),
                                update={"Language": sources.LANG_LOP[lang]},
                            )
                            related_riding.names[lang][sources.NAME_LOP_RIDING_HISTORY[lang]] = BeautifulSoup(
                                fetch_url(related_riding.links[lang][sources.NAME_LOP_RIDING_HISTORY[lang]]),
                                "html.parser",
                            ).select("h4")[0].text.split(", ")[0]
                            related_riding.save()
                    riding.related_historically.add(related_riding)

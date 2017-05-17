from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url
from parliaments import models
from tqdm import tqdm
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    known_ridings = set()
    cache_provinces = {}

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        pending_parliaments = models.Parliament.objects.filter(general_election__election_ridings__isnull=True)
        if pending_parliaments.exists():
            for parliament in tqdm(
                pending_parliaments,
                desc="Fetch Ridings, LoP",
                unit="parliament",
            ):
                self.fetch_ridings(parliament)

    @transaction.atomic
    def fetch_ridings(self, parliament):
        logger.debug("Fetch ridings, {}".format(parliament))
        skipped_codes = set()
        codes_to_ridings = dict()
        soup = BeautifulSoup(
            fetch_url(parliament.links[EN][sources.NAME_LOP_PARLIAMENT[EN]], use_cache=True),
            "html.parser",
        )
        for select in (
            "#ctl00_cphContent_ctl04_repGeneralElection_ctl00_grdMembers tr",
            "#ctl00_cphContent_ctl04_pnlSectionByElectionContent tr",
        ):
            for row in soup.select(select):
                cells = row.find_all("td", recursive=False)
                if cells:
                    riding_name, province_name = sources.LOP_RIDING_AND_PROVINCE.search(cells[1].text.strip()).groups()
                    province_slug = slugify(province_name)
                    riding_slug = slugify(" ".join((province_slug, riding_name)))
                    code = sources.LOP_CODE.search(cells[0].a.attrs["href"]).group().lower()
                    if riding_slug not in self.known_ridings:
                        try:
                            province = self.cache_provinces[province_slug]
                        except KeyError:
                            province = models.Province.objects.get(slug=province_slug)
                            self.cache_provinces[province_slug] = province
                        riding, created = models.Riding.objects.get_or_create(
                            slug=riding_slug,
                            province=province,
                        )
                        if created:
                            riding.names[EN][sources.NAME_LOP_PARLIAMENT[EN]] = riding_name
                            riding.save()
                        self.known_ridings.add(riding_slug)
                        codes_to_ridings[code] = riding
                    else:
                        skipped_codes.add(code)

        soup = BeautifulSoup(
            fetch_url(parliament.links[FR][sources.NAME_LOP_PARLIAMENT[FR]], use_cache=True),
            "html.parser",
        )
        for select in (
            "#ctl00_cphContent_ctl04_repGeneralElection_ctl00_grdMembers tr",
            "#ctl00_cphContent_ctl04_pnlSectionByElectionContent tr",
        ):
            for row in soup.select(select):
                cells = row.find_all("td", recursive=False)
                if cells:
                    code = sources.LOP_CODE.search(cells[0].a.attrs["href"]).group().lower()
                    if code not in skipped_codes:
                        riding_name, province_name = sources.LOP_RIDING_AND_PROVINCE.search(cells[1].text.strip()).groups()
                        riding = codes_to_ridings[code]
                        riding.names[FR][sources.NAME_LOP_PARLIAMENT[FR]] = riding_name
                        riding.save()

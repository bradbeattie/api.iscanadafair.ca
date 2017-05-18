from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from federal_common import sources
from federal_common.sources import EN
from federal_common.utils import fetch_url, dateparse, REVERSE_ORDINAL
from parliaments import models
from tqdm import tqdm
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)
        pending_parliaments = models.Parliament.objects.filter(
            Q(sessions__isnull=True) | Q(number__gte=models.Parliament.objects.last().number - 1)
        )
        if pending_parliaments.exists():
            for parliament in tqdm(
                pending_parliaments,
                desc="Fetch Sessions, LoP",
                unit="parliament",
            ):
                self.fetch_sessions(parliament)

    def fetch_sessions(self, parliament):
        logger.debug("Fetch sessions: {}".format(parliament))
        soup = BeautifulSoup(fetch_url(
            parliament.links[EN][sources.NAME_LOP_PARLIAMENT[EN]],
        ), "html.parser")

        for row in soup.select("#ctl00_cphContent_ctl00_grdSessionList tr"):
            if row.attrs["class"] != ["GridHeader"]:
                cells = row.find_all("td")
                date_start = cells[1].text.split(" - ")[0].strip()
                date_end = cells[1].text.split(" - ")[1].strip()
                session_number = int(REVERSE_ORDINAL.sub(r"\1", cells[0].text.strip()))
                models.Session.objects.get_or_create(
                    slug="{}-{}".format(parliament.number, session_number),
                    parliament=parliament,
                    number=session_number,
                    date_start=dateparse(date_start),
                    date_end=dateparse(date_end) if date_end else None,
                    sittings_senate=int(cells[3].text),
                    sittings_house=int(cells[4].text),
                )

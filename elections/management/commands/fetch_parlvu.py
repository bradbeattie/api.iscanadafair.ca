from bs4 import BeautifulSoup, Tag
from datetime import datetime, date
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from elections import get_by_name_variant
from elections import models
from elections.utils import fetch_url, one_or_none
from pprint import pprint
from urllib.parse import urlparse, parse_qs
import json
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        logger.info("Fetch ParlVu")

        year = date.today().year
        for year in range(date.today().year, date.today().year - 50, -1):
            days = json.loads(fetch_url(
                "http://parlvu.parl.gc.ca/XRender/en/api/Data/GetCalendarYearData/{}0101/-1".format(year),
                force_load=year >= 2017
            ))
            if not len(days):
                break
            for day in days:
                self.fetch_day(datetime.strptime(day, "%Y-%m-%dT%H:%M:%S").date())

    def fetch_day(self, day):
        events = json.loads(fetch_url(
            "http://parlvu.parl.gc.ca/XRender/en/api/Data/GetContentEntityByYMD/{}/-1".format(day.strftime("%Y%m%d"))
        ))
        pprint(events, width=200)

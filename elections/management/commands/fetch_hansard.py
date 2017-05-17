from bs4 import BeautifulSoup, Tag
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from django.db.models import Q
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from elections import models
from elections.utils import fetch_url, one_or_none
from elections import get_by_name_variant
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        logger.info("Fetch hansard")

        for session_link in BeautifulSoup(fetch_url(
            "http://www.parl.gc.ca/housechamberbusiness/ChamberSittings.aspx",
            force_load=not settings.DEBUG,
            allow_redirects=True,
        ), "html.parser").select("a.MenuParliamentSessionLink"):
            url = "http://www.parl.gc.ca/housechamberbusiness/{}".format(session_link.attrs["href"])
            session = models.Session.objects.get(
                parliament__number=parse_qs(urlparse(url).query)["Parl"][0],
                number=parse_qs(urlparse(url).query)["Ses"][0],
            )
            session.links["Parliament, Hansard"] = url
            session.save()

            # Seems XML Hansards are only available from the 39th on
            if session.parliament.number >= 39:
                self.get_hansard_session(session)

    def get_hansard_session(self, session):
        logger.info(session)
        for year in BeautifulSoup(fetch_url(
            session.links["Parliament, Hansard"],
            force_load=not settings.DEBUG,
            allow_redirects=True,
        ), "html.parser").select("#ctl00_PageContent_divTabbedYears a"):
            for day in BeautifulSoup(fetch_url(
                "http://www.parl.gc.ca/housechamberbusiness/{}".format(year.attrs["href"]),
                force_load=not settings.DEBUG,
                allow_redirects=True,
            ), "html.parser").select("a.PublicationCalendarLink"):
                url = "http://www.parl.gc.ca{}".format(day.attrs["href"])
                hansard_soup = BeautifulSoup(fetch_url("{}&xml=true".format(url)), "lxml")
                logger.info(hansard_soup.select("extracteditem[name=Date]")[0].text)

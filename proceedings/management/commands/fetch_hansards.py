from bs4 import BeautifulSoup, Tag
from datetime import datetime
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from elections import models
from federal_common.utils import fetch_url, url_tweak
from urllib.parse import urljoin
from urllib.parse import urlparse, parse_qs
import asyncio
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        logger.info("Fetch hansard")

        for session_link in BeautifulSoup(fetch_url(
            "http://www.ourcommons.ca/documentviewer/en/house/latest-sitting",
            allow_redirects=True,
            use_cache=False,
        ), "html.parser").select(".session-selector-session a"):
            session_url = url_tweak(
                "http://www.ourcommons.ca/DocumentViewer/en/SessionPublicationCalendarsWidget?organization=HOC&publicationTypeId=191",
                update={
                    "parliament": session_link.attrs["data-parliament"],
                    "session": session_link.attrs["data-session"],
                },
            )
            sittings_links = (
                urljoin(session_url, sitting_link.attrs["href"])
                for sitting_link in BeautifulSoup(fetch_url(
                    session_url,
                    use_cache=int(session_link.attrs["data-parliament"]) < 42,
                ), "html.parser").select("td a")
            )

    def parse_sitting_links(self, sitting_links):
        async def fetch_hansard(sitting_link):
            soup = BeautifulSoup(await fetch_url(
                urljoin(session_url, sitting_link.attrs["href"]),
                use_cache=int(session_link.attrs["data-parliament"]) < 42,
            ), "html.parser")
            print(soup.select("#load-publication-selector")[0].text)

        loop = asyncio.get_event_loop()
        for sitting_link in sitting_links:
            loop.run_until_complete(fetch_hansard(sitting_link))
        loop.close()

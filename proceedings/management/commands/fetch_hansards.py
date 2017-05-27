from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak, dateparse, one_or_none, get_french_parl_url
from parliaments.models import Session
from proceedings import models
from tqdm import tqdm
from urllib.parse import urljoin
import concurrent.futures
import logging
import re


logger = logging.getLogger(__name__)
SITTING = re.compile(r"/sitting-([0-9]+[a-z]?)/", re.I)


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        for session_link in tqdm(
            BeautifulSoup(fetch_url(
                "http://www.ourcommons.ca/documentviewer/en/house/latest-sitting",
                allow_redirects=True,
                use_cache=False,
            ), "html.parser").select(".session-selector"),
            desc="Fetch Sittings, HoC",
            unit="session",
        ):
            session = Session.objects.get(
                parliament__number=session_link.attrs["data-parliament"],
                number=session_link.attrs["data-session"],
            )
            self.parse_session(session)

    @transaction.atomic
    def parse_session(self, session):
        session_url = url_tweak(
            "http://www.ourcommons.ca/DocumentViewer/en/SessionPublicationCalendarsWidget?organization=HOC&publicationTypeId=37",
            update={"parliament": session.parliament.number, "session": session.number},
        )
        sitting_urls = (
            urljoin(session_url, sitting_link.attrs["href"])
            for sitting_link in BeautifulSoup(fetch_url(
                session_url,
                use_cache=session.parliament.number < 42,
            ), "html.parser").select("td a")
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
            future_to_url = {
                executor.submit(self.parse_sitting_url, sitting_url, session): sitting_url
                for sitting_url in sitting_urls
            }
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                future.result()

    def parse_sitting_url(self, sitting_url, session):
        soup = BeautifulSoup(fetch_url(sitting_url), "html.parser")
        sitting, created = models.Sitting.objects.get_or_create(
            session=session,
            number=SITTING.search(sitting_url).groups()[0].lower(),
            date=dateparse(soup.select("#load-publication-selector")[0].text),
        )
        for lang in (EN, FR):
            for tab in soup.select(".publication-tabs > li"):
                if "disabled" not in tab["class"]:
                    sitting.links[lang][", ".join((sources.NAME_HOC[lang], tab.a.text))] = urljoin(
                        sitting_url,
                        tab.a.attrs.get("href", sitting_url)
                    )
            if lang == EN:
                soup = BeautifulSoup(fetch_url(get_french_parl_url(sitting_url, soup)), "html.parser")
        sitting.save()

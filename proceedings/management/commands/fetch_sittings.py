from bs4 import BeautifulSoup
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak, dateparse, one_or_none, get_french_parl_url
from parliaments.models import Session
from proceedings import models
from tqdm import tqdm
from urllib.parse import urljoin
import logging
import re


logger = logging.getLogger(__name__)
SITTING = re.compile(r"/sitting-([0-9]+[a-z]?)/", re.I)
CACHE_BEFORE = timedelta(days=7 if settings.DEBUG else 90)
NUMBERS = re.compile(r"([0-9]+)")


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        for session_link in tqdm(
            BeautifulSoup(fetch_url(
                "http://www.ourcommons.ca/DocumentViewer/en/42-1/house/sitting-1/hansard",
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
        for sitting_link in tqdm(
            BeautifulSoup(fetch_url(
                session_url,
                use_cache=session.parliament.number < 42,
            ), "html.parser").select("td a"),
            desc=str(session),
            unit="sitting",
        ):
            self.parse_sitting_url(urljoin(session_url, sitting_link.attrs["href"]), session)

    def parse_sitting_url(self, sitting_url, session):
        try:
            sitting_number = SITTING.search(sitting_url).groups()[0].upper()
            sitting = models.Sitting(
                session=session,
                number=sitting_number,
                slug="-".join((session.slug, sitting_number.lower())),
            )
            for lang in (EN, FR):
                soup = BeautifulSoup(fetch_url(
                    sitting_url,
                    use_cache=(session.parliament.number, int(NUMBERS.search(sitting.number).groups()[0])) < (42, 190),
                ), "html.parser")
                if lang == EN:
                    sitting.date = dateparse(soup.select("#load-publication-selector")[0].text)
                for tab in soup.select(".publication-tabs > li"):
                    if "disabled" not in tab["class"]:
                        sitting.links[lang][", ".join((sources.NAME_HOC[lang], tab.a.text))] = urljoin(
                            sitting_url,
                            tab.a.attrs.get("href", sitting_url)
                        )
                        if lang == EN and "Hansard" in tab.a.text:
                            sitting.links[EN][sources.NAME_OP[EN]] = f"https://openparliament.ca/debates/{sitting.date.year}/{sitting.date.month}/{sitting.date.day}/"
                xml_button = one_or_none(soup.select(".btn-export-xml"))
                if xml_button:
                    xml_url = urljoin(sitting_url, xml_button.attrs["href"])
                    sitting.links[lang][sources.NAME_HOC_HANSARD_XML[lang]] = xml_url
                    fetch_url(xml_url, discard_content=True)
                if lang == EN:
                    sitting_url = get_french_parl_url(sitting_url, soup)
            sitting.save()
        except Exception as e:
            logger.exception(e)

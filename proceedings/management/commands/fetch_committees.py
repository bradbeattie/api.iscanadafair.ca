from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak, get_french_parl_url
from parliaments.models import Session
from proceedings import models
from tqdm import tqdm
from urllib.parse import parse_qs, urlparse
from urllib.parse import urljoin
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)
        self.fetch_hoc_committees()
        self.fetch_senate_committees()

    @transaction.atomic
    def fetch_hoc_committees(self):
        list_url = "http://www.ourcommons.ca/Committees/en/List"
        for link in tqdm(
            BeautifulSoup(
                fetch_url(list_url),
                "html.parser",
            ).select(".session-selector"),
            desc="Fetch Committees, HoC",
            unit="session",
        ):
            querydict = parse_qs(urlparse(link.attrs["href"]).query)
            self.fetch_hoc_committees_session(
                Session.objects.get(parliament__number=querydict["parl"][0], number=querydict["session"][0]),
                url_tweak(urljoin(list_url, link.attrs["href"])),
            )

    @transaction.atomic
    def fetch_senate_committees(self):
        list_url = "https://sencanada.ca/en/committees/"
        for link in tqdm(
            BeautifulSoup(
                fetch_url(list_url),
                "html.parser",
            ).select(".session-dropdown-session a"),
            desc="Fetch Committees, Senate",
            unit="session",
        ):
            parliament_number, session_number = link.attrs["href"].strip("/").rsplit("/", 1)[1].split("-")
            self.fetch_senate_committees_session(
                Session.objects.get(parliament__number=parliament_number, number=session_number),
                url_tweak(urljoin(list_url, link.attrs["href"])),
            )

    def fetch_hoc_committees_session(self, session, session_url):
        for link in tqdm(
            BeautifulSoup(
                fetch_url(session_url, use_cache=True),
                "html.parser",
            ).select(".committees-list .accordion-content a"),
            desc=str(session),
            unit="committee",
        ):
            committee_url = {EN: url_tweak(urljoin(session_url, link.attrs["href"]))}
            committee = models.Committee(
                session=session,
                chamber=models.Committee.CHAMBER_HOC,
            )
            for lang in (EN, FR):
                soup = BeautifulSoup(fetch_url(committee_url[lang]), "html.parser")
                committee.names[lang][sources.NAME_PARL_COMMITTEE[lang]] = soup.select(".institution-brand")[0].text
                committee.names[lang][sources.NAME_PARL_COMMITTEE_CODE[lang]] = soup.select(".header-title.current-committee-profile")[0].text
                committee.links[lang][sources.NAME_PARL_COMMITTEE[lang]] = committee_url[lang]
                if not committee.slug:
                    if "Joint" in committee.names[lang][sources.NAME_PARL_COMMITTEE[lang]]:
                        committee.chamber = models.Committee.CHAMBER_JOINT
                    committee.slug = self.get_slug(committee)
                    committee_url[FR] = get_french_parl_url(committee_url[lang], soup)
            committee.save()

    def fetch_senate_committees_session(self, session, session_url):
        for link in tqdm(
            BeautifulSoup(
                fetch_url(session_url, use_cache=True),
                "html.parser",
            ).select(".committee-list-boxes-wrapper a"),
            desc=str(session),
            unit="committee",
        ):
            committee_url = {EN: url_tweak(urljoin(session_url, link.attrs["href"]))}
            if link.select(".joint-committee-list-boxes"):
                logger.debug("Skipping {} (broken, reported, joint committees are covered in HoC anyway)".format(committee_url[EN]))
                continue

            committee = models.Committee(
                session=session,
                chamber=models.Committee.CHAMBER_SEN,
            )
            for lang in (EN, FR):
                soup = BeautifulSoup(fetch_url(committee_url[lang]), "html.parser")
                committee.names[lang][sources.NAME_PARL_COMMITTEE[lang]] = soup.select("meta[name=dc.description]")[0].attrs["content"]
                committee.names[lang][sources.NAME_PARL_COMMITTEE_CODE[lang]] = committee_url[lang].strip("/").split("/")[-2].upper()
                committee.links[lang][sources.NAME_PARL_COMMITTEE[lang]] = committee_url[lang]
                if not committee.slug:
                    committee.slug = self.get_slug(committee)
                    committee_url[FR] = get_french_parl_url(committee_url[lang], soup)
            committee.save()

    def get_slug(self, committee):
        return slugify("-".join(map(lambda x: str(x), (
            committee.names[EN][sources.NAME_PARL_COMMITTEE_CODE[EN]],
            committee.session.parliament.number,
            committee.session.number,
            {
                models.Committee.CHAMBER_HOC: "hoc",
                models.Committee.CHAMBER_SEN: "sen",
                models.Committee.CHAMBER_JOINT: "joint",
            }[committee.chamber],
        ))))

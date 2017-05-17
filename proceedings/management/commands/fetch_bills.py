from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak, get_cached_dict, get_cached_obj
from parliaments.models import Session
from proceedings import models
from tqdm import tqdm
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        list_url = "http://www.parl.gc.ca/LegisInfo/Home.aspx?Page=1"
        for link in tqdm(
            BeautifulSoup(
                fetch_url(list_url, allow_redirects=True),
                "html.parser",
            ).select("#ctl00_PageContentSection_BillListingControl_BillFacetSearch_SessionSelector1_pnlSessions a"),
            desc="Fetch Bills, LEGISinfo",
            unit="session",
        ):
            if " - " in link.text:
                parliament_number, session_number = link.text.split()[0].split("-")
                self.fetch_bills_session(Session.objects.get(parliament__number=parliament_number, number=session_number))

    @transaction.atomic
    def fetch_bills_session(self, session):
        cached_committees = get_cached_dict(models.Committee.objects.filter(session=session))

        url = "http://www.parl.ca/LegisInfo/Home.aspx?download=xml&ParliamentSession={}-{}".format(session.parliament.number, session.number)
        soup = BeautifulSoup(fetch_url(url, use_cache=session.parliament.number >= 42), "lxml")
        for bill_soup in tqdm(
            soup.find_all("bill"),
            desc=str(session),
            unit="bill",
        ):
            bill_number = bill_soup.select("billnumber")[0]
            bill_number = "-".join(filter(None, (
                bill_number.attrs["prefix"],
                bill_number.attrs["number"],
                bill_number.get("suffix", None),
            )))
            bill = models.Bill(
                session=session,
                slug=slugify("-".join(map(lambda x: str(x), (
                    session.parliament.number,
                    session.number,
                    bill_number,
                )))),
            )
            for lang in (EN, FR):
                bill.links[lang][sources.NAME_LEGISINFO[lang]] = url_tweak(
                    "http://www.parl.gc.ca/LegisInfo/BillDetails.aspx",
                    update={
                        "billId": bill_soup.attrs["id"],
                        "Language": sources.LANG_LEGISINFO_UI[lang],
                    },
                )
                bill.names[lang][sources.NAME_LEGISINFO_NUMBER[lang]] = bill_number
                bill.names[lang][sources.NAME_LEGISINFO_TITLE[lang]] = bill_soup.select("billtitle > title[language={}]".format(sources.LANG_LEGISINFOL_XML[lang]))[0].text
                title_short = bill_soup.select("shorttitle > title[language={}]".format(sources.LANG_LEGISINFOL_XML[lang]))[0].text
                if title_short:
                    bill.names[lang][sources.NAME_LEGISINFO_TITLE_SHORT[lang]] = title_short
            bill.save()

            for event_soup in bill_soup.select("event"):
                try:
                    committee_soup = bill_soup.select("committee[accronym]")[0]  # They misspelled "acronym" in their XML
                    code = committee_soup.attrs["accronym"]
                    if code != "WHOL":
                        bill.committees.add(get_cached_obj(cached_committees, code))
                except IndexError:
                    pass

from bs4 import BeautifulSoup, Tag
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

    parliamentarian_cache = {}
    party_cache = {}
    riding_cache = {}
    province_cache = {}
    committee_cache = {}

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        logger.info("Fetch parliament")
        self.fetch_bills()
        self.fetch_chamber_votes()

    def fetch_bills(self):
        for session_link in BeautifulSoup(fetch_url(
            "http://www.parl.gc.ca/LegisInfo/Home.aspx?Page=1",
            force_load=not settings.DEBUG,
            allow_redirects=True,
        ), "html.parser").select("#ctl00_PageContentSection_BillListingControl_BillFacetSearch_SessionSelector1_pnlSessions a"):
            if " - " in session_link.text:
                parliament_number, session_number = session_link.text.split()[0].split("-")
                session = models.Session.objects.get(parliament__number=parliament_number, number=session_number)
                self.fetch_bills_session(session)

    @transaction.atomic
    def fetch_bills_session(self, session):
        logger.info("Fetch bills {}".format(session))
        soup = BeautifulSoup(fetch_url(
            "http://www.parl.gc.ca/LegisInfo/Home.aspx?ParliamentSession={}-{}&download=xml".format(
                session.parliament.number,
                session.number,
            ),
            force_load=not settings.DEBUG,
        ), "lxml")
        for bill_soup in soup.find_all("bill"):
            bill, created = models.Bill.objects.get_or_create(
                session=session,
                code_letter=bill_soup.select("billnumber")[0].attrs["prefix"],
                code_number=bill_soup.select("billnumber")[0].attrs["number"],
                defaults={
                    "title": bill_soup.select("billtitle > title[language=en]")[0].text,
                    "short_title": bill_soup.select("shorttitle > title[language=en]")[0].text,
                    "links": {
                        "Parliament, Bills": "http://www.parl.gc.ca/LegisInfo/BillDetails.aspx?billId={}".format(bill_soup.attrs["id"]),
                    },
                }
            )
            for event_soup in bill_soup.select("event"):
                try:
                    committee_soup = bill_soup.select("committee[accronym]")[0]  # They misspelled "acronym" in their XML
                    code = committee_soup.attrs["accronym"]
                    chamber = event_soup.attrs["chamber"]
                    committee = self.committee_cache[code]
                except KeyError:
                    title = committee_soup.select("title[language=en]")[0].text
                    committee, created = models.Committee.objects.get_or_create(
                        code=code,
                        name=title,
                        chamber={
                            "HOC": models.Committee.CHAMBER_HOC,
                            "SEN": models.Committee.CHAMBER_SEN,
                        }[chamber],
                    )
                    if committee.chamber == models.Committee.CHAMBER_HOC:
                        committee.links["House of Commons"] = "http://www.parl.gc.ca/Committees/en/{}".format(code)
                    else:
                        committee.links["Senate"] = "https://sencanada.ca/en/committees/{}".format(code.lower())
                    committee.save()
                    self.committee_cache[code] = committee
                except IndexError:
                    continue
                bill.committees.add(committee)

    def fetch_chamber_votes(self):
        parl_soup = BeautifulSoup(fetch_url(
            "http://www.parl.gc.ca/HouseChamberBusiness/ChamberVoteList.aspx?Language=E",
            force_load=not settings.DEBUG
        ), "html.parser")
        for option in parl_soup.select("#ctl00_PageContent_voteListingFilterControl_ddlParliamentSession option"):
            parliament_number, session_number = option.attrs["value"].split(",")
            parliament = models.Parliament.objects.get(number=parliament_number)
            session = models.Session.objects.get(parliament=parliament, number=session_number)
            self.fetch_votes_session(session)

    def fetch_votes_session(self, session):
        logger.info(session)
        session.links["Chamber Votes"] = "http://www.parl.gc.ca/HouseChamberBusiness/Chambervotelist.aspx?Language=E&Parl={}&Ses={}".format(
            session.parliament.number,
            session.number,
        )
        session.save()
        parl_soup = BeautifulSoup(fetch_url(
            "{}&xml=True".format(session.links["Chamber Votes"]),
            force_load=not settings.DEBUG
        ), "lxml")
        for vote_soup in parl_soup.find_all("vote"):
            sitting, created = models.Sitting.objects.get_or_create(
                session=session,
                number=vote_soup.attrs["sitting"],
                date=datetime.strptime(vote_soup.attrs["date"], "%Y-%m-%d").date(),
            )
            try:
                code_letter, code_number = vote_soup.find("relatedbill").attrs["number"].split("-")
                bill = models.Bill.objects.get(session=session, code_letter=code_letter, code_number=code_number)
            except:
                bill = None
            sitting_vote, created = models.SittingVote.objects.get_or_create(
                sitting=sitting,
                number=vote_soup.attrs["number"],
                defaults={
                    "bill": bill,
                    "links": {
                        "Parliament, Chamber Vote Detail": "http://www.parl.gc.ca/HouseChamberBusiness/Chambervotedetail.aspx?FltrParl={}&FltrSes={}&vote={}".format(
                            session.parliament.number,
                            session.number,
                            vote_soup.attrs["number"],
                        ),
                    },
                },
            )
            self.fetch_vote(sitting_vote)

    @transaction.atomic
    def fetch_vote(self, sitting_vote):
        logger.info(sitting_vote)
        search_name_source = "Parliament, Chamber Vote Detail"
        vote_soup = BeautifulSoup(fetch_url(
            "{}&xml=True".format(sitting_vote.links[search_name_source]),
            force_load=not settings.DEBUG
        ), "lxml")
        vote_mapping = {
            "nay": models.SittingVoteParticipant.VOTE_NAY,
            "yea": models.SittingVoteParticipant.VOTE_YEA,
            "paired": models.SittingVoteParticipant.VOTE_PAIRED,
        }
        for participant_soup in vote_soup.select("participant"):

            parliamentarian_name = participant_soup.find("name").text
            riding_name = participant_soup.find("constituency").text
            province_name = participant_soup.find("province").text
            party_name = participant_soup.find("party").text

            try:
                province = self.province_cache[province_name]
            except KeyError:
                province = get_by_name_variant.get_province(
                    name=province_name,
                    search_name_source=search_name_source,
                )
                self.province_cache[province_name] = province

            try:
                parliamentarian = self.parliamentarian_cache[(parliamentarian_name, riding_name)]
            except KeyError:
                parliamentarian = get_by_name_variant.get_parliamentarian(
                    election_candidates__election_riding__riding__province=province,
                    name=parliamentarian_name,
                    search_name_source=search_name_source,
                )
                self.parliamentarian_cache[(parliamentarian_name, riding_name)] = parliamentarian

            try:
                party = self.party_cache[party_name]
            except KeyError:
                try:
                    party = get_by_name_variant.get_party(
                        name=party_name,
                        search_name_source=search_name_source,
                    )
                except get_by_name_variant.SkippedObject:
                    party = None
                self.party_cache[party_name] = party

            try:
                voted = one_or_none(
                    vote_mapping[choice.name]
                    for choice in participant_soup.find("recordedvote").contents
                    if isinstance(choice, Tag) and choice.text == "1"
                )
            except AssertionError:
                voted = models.SittingVoteParticipant.VOTE_ABSTAINED

            models.SittingVoteParticipant.objects.get_or_create(
                sitting_vote=sitting_vote,
                parliamentarian=parliamentarian,
                party=party,
                defaults={
                    "recorded_vote": voted,
                },
            )

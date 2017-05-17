from bs4 import BeautifulSoup
from urllib.parse import parse_qs, urlparse
from django.core.management.base import BaseCommand
from django.db import transaction
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak, get_french_parl_url
from parliaments.models import Session
from tqdm import tqdm
import logging
import re


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        list_url = "http://www.ourcommons.ca/Parliamentarians/en/HouseVotes/Index"
        parl_soup = BeautifulSoup(fetch_url(list_url), "html.parser")

        # Super-irritating that Parliament uses parliament=X&session=Y in some places, but then session=PK in others
        default_session_id = parse_qs(urlparse(parl_soup.select(".refiner-display-daterange .refinement a")[0].attrs["href"]).query)["sessionId"][0]

        for link in tqdm(
            parl_soup.select(".refiner-display-parliament .refinement a"),
            desc="Fetch Votes, HoC",
            unit="session",
        ):
            groupdict = re.search(r"(?P<parliament>[345][0-9])(st|nd|rd|th) Parliament\s+(?P<session>[1-9])(st|nd|rd|th)\s+", link.text).groupdict()
            self.fetch_votes_session(
                Session.objects.get(
                    parliament__number=groupdict["parliament"],
                    number=groupdict["session"],
                ),
                list_url,
                parse_qs(urlparse(link.attrs["href"]).query).get("sessionId", [default_session_id])[0],
            )

    def fetch_votes_session(self, session, list_url, remote_session_id):
        session.links[EN][sources.NAME_HOC_VOTES[EN]] = url_tweak(list_url, update={"sessionId": remote_session_id})
        session.links[FR][sources.NAME_HOC_VOTES[FR]] = get_french_parl_url(
            session.links[EN][sources.NAME_HOC_VOTES[EN]],
            BeautifulSoup(fetch_url(session.links[EN][sources.NAME_HOC_VOTES[EN]], use_cache=True), "lxml"),
        )
        session.save()

        parl_soup = BeautifulSoup(fetch_url(url_tweak(
            "http://www.ourcommons.ca/Parliamentarians/en/HouseVotes/ExportVotes?output=XML",
            update={"sessionId": remote_session_id},
        ), use_cache=session.parliament.number < 42), "lxml")
        for vote_number, vote_soup in enumerate(tqdm(
            parl_soup.find_all("voteparticipant"),  # Oddly named considering the previous format we found this in
            desc=str(session),
            unit="vote",
        )):
            print(vote_number, vote_soup.decisiondivisionsubject.text)
        raise Exception(123)
#            sitting, created = models.Sitting.objects.get_or_create(
#                session=session,
#                number=vote_soup.attrs["sitting"],
#                date=datetime.strptime(vote_soup.attrs["date"], "%Y-%m-%d").date(),
#            )
#            try:
#                code_letter, code_number = vote_soup.find("relatedbill").attrs["number"].split("-")
#                bill = models.Bill.objects.get(session=session, code_letter=code_letter, code_number=code_number)
#            except:
#                bill = None
#            sitting_vote, created = models.SittingVote.objects.get_or_create(
#                sitting=sitting,
#                number=vote_soup.attrs["number"],
#                defaults={
#                    "bill": bill,
#                    "links": {
#                        "Parliament, Chamber Vote Detail": "http://www.parl.gc.ca/HouseChamberBusiness/Chambervotedetail.aspx?FltrParl={}&FltrSes={}&vote={}".format(
#                            session.parliament.number,
#                            session.number,
#                            vote_soup.attrs["number"],
#                        ),
#                    },
#                },
#            )
#            self.fetch_vote(sitting_vote)
#
#    @transaction.atomic
#    def fetch_vote(self, sitting_vote):
#        logger.info(sitting_vote)
#        search_name_source = "Parliament, Chamber Vote Detail"
#        vote_soup = BeautifulSoup(fetch_url(
#            "{}&xml=True".format(sitting_vote.links[search_name_source]),
#            force_load=not settings.DEBUG
#        ), "lxml")
#        vote_mapping = {
#            "nay": models.SittingVoteParticipant.VOTE_NAY,
#            "yea": models.SittingVoteParticipant.VOTE_YEA,
#            "paired": models.SittingVoteParticipant.VOTE_PAIRED,
#        }
#        for participant_soup in vote_soup.select("participant"):
#
#            parliamentarian_name = participant_soup.find("name").text
#            riding_name = participant_soup.find("constituency").text
#            province_name = participant_soup.find("province").text
#            party_name = participant_soup.find("party").text
#
#            try:
#                province = self.province_cache[province_name]
#            except KeyError:
#                province = get_by_name_variant.get_province(
#                    name=province_name,
#                    search_name_source=search_name_source,
#                )
#                self.province_cache[province_name] = province
#
#            try:
#                parliamentarian = self.parliamentarian_cache[(parliamentarian_name, riding_name)]
#            except KeyError:
#                parliamentarian = get_by_name_variant.get_parliamentarian(
#                    election_candidates__election_riding__riding__province=province,
#                    name=parliamentarian_name,
#                    search_name_source=search_name_source,
#                )
#                self.parliamentarian_cache[(parliamentarian_name, riding_name)] = parliamentarian
#
#            try:
#                party = self.party_cache[party_name]
#            except KeyError:
#                try:
#                    party = get_by_name_variant.get_party(
#                        name=party_name,
#                        search_name_source=search_name_source,
#                    )
#                except get_by_name_variant.SkippedObject:
#                    party = None
#                self.party_cache[party_name] = party
#
#            try:
#                voted = one_or_none(
#                    vote_mapping[choice.name]
#                    for choice in participant_soup.find("recordedvote").contents
#                    if isinstance(choice, Tag) and choice.text == "1"
#                )
#            except AssertionError:
#                voted = models.SittingVoteParticipant.VOTE_ABSTAINED
#
#            models.SittingVoteParticipant.objects.get_or_create(
#                sitting_vote=sitting_vote,
#                parliamentarian=parliamentarian,
#                party=party,
#                defaults={
#                    "recorded_vote": voted,
#                },
#            )

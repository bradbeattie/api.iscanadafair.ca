from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak, get_french_parl_url, dateparse, one_or_none, soup_to_text
from parliaments.models import Session, Parliamentarian, Party
from proceedings import models
from tqdm import tqdm
from unidecode import unidecode
from urllib.parse import parse_qs, urlparse
import json
import logging
import re


logger = logging.getLogger(__name__)
RESULT_MAPPING = {
    "Negatived": models.HouseVote.RESULT_NEGATIVED,
    "Agreed To": models.HouseVote.RESULT_AGREED_TO,
    "Tie": models.HouseVote.RESULT_TIE,
}
VOTE_MAPPING = {
    "nay": models.HouseVoteParticipant.VOTE_NAY,
    "yea": models.HouseVoteParticipant.VOTE_YEA,
    "paired": models.HouseVoteParticipant.VOTE_PAIRED,
}
HONORIFIC = re.compile(r"^(Mr|Mrs|Ms)\. ")
PARTY_MAPPING = {
    "Bloc Québécois": "bq",
    "Conservative": "c",
    "Liberal": "lib",
    "NDP": "ndp",
    "Green Party": "gp",
    "Forces et Démocratie": "sd",
}
RECORDED_VOTE_MAPPING = {
    (False, False, True): models.HouseVoteParticipant.VOTE_PAIRED,
    (False, True, False): models.HouseVoteParticipant.VOTE_NAY,
    (True, False, False): models.HouseVoteParticipant.VOTE_YEA,
    (True, True, False): models.HouseVoteParticipant.VOTE_ABSTAINED,
}
PARLIAMENTARIAN_MAPPING = {
    "Ms. Khristinn Kellie Leitch": "Kellie Leitch",
}


class Command(BaseCommand):

    party_cache = {
        "Independent": None,
        "Conservative Independent": None,
    }
    parliamentarian_cache = {}

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

        for overview in tqdm(
            parl_soup.find_all("voteparticipant"),  # Oddly named considering the previous format we found this in
            desc=str(session),
            unit="vote",
        ):
            self.fetch_vote(overview, session)

    @transaction.atomic
    def fetch_vote(self, overview, session):
        number = overview.decisiondivisionnumber.text
        vote = models.HouseVote(
            slug="-".join((session.slug, number)),
            number=number,
            result=RESULT_MAPPING[overview.decisionresultname.text],
        )
        vote.links[EN][sources.NAME_HOC_VOTE_DETAILS[EN]] = "http://www.ourcommons.ca/Parliamentarians/en/votes/{}/{}/{}/".format(
            session.parliament.number,
            session.number,
            number,
        )
        soup = {}
        for lang in (EN, FR):
            soup[lang] = BeautifulSoup(
                fetch_url(vote.links[lang][sources.NAME_HOC_VOTE_DETAILS[lang]]),
                "html.parser",
            )
            details = one_or_none(soup[lang].select(".voteDetailsText"))
            if details:
                vote.context[lang] = soup_to_text(details)
            if lang == EN:
                vote.links[FR][sources.NAME_HOC_VOTE_DETAILS[FR]] = get_french_parl_url(
                    vote.links[lang][sources.NAME_HOC_VOTE_DETAILS[lang]],
                    soup[lang],
                )
        try:
            vote.sitting = models.Sitting.objects.get(
                session=session,
                date=dateparse(overview.decisioneventdatetime.text),
            )
        except Exception as e:
            # Sometimes the XML listings show the wrong dates.
            # I've contacted infonet@parl.gc.ca about this.
            element = BeautifulSoup(
                fetch_url(vote.links[EN][sources.NAME_HOC_VOTE_DETAILS[EN]]),
                "html.parser",
            ).select("#VoteDetailsHeader .voteDetailsTopHeaderContent")[1]
            vote.sitting = models.Sitting.objects.get(
                session=session,
                date=dateparse(element.text.split(" - ")[1]),
            )

        if overview.billnumbercode.text:
            vote.bill = models.Bill.objects.get(slug="-".join((session.slug, *overview.billnumbercode.text.split("-"))))

        vote.save()

        # Fetch the parliamentarian votes
        # TODO: This has been temporarily disabled until party affiliation
        #       is reinstated. In the interim, I'll scrape off the HTML instead.
#        vote_xml = BeautifulSoup(
#            fetch_url(url_tweak("http://www.ourcommons.ca/Parliamentarians/en/HouseVotes/ExportDetailsVotes?output=XML", update={
#                "parliament": session.parliament.number,
#                "session": session.number,
#                "vote": vote.number,
#            })),
#            "lxml",
#        )
#        for participant_soup in vote_xml.find_all("voteparticipant"):
#            print("SOUP", participant_soup)
#            parliamentarian_name = participant_soup.find("name").text
#            riding_name = participant_soup.find("constituencyname").text
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

        print(vote)
        for row in soup[EN].select("#parlimant > tbody > tr"):  # Note the source code misspells "parliament"
            hvp = models.HouseVoteParticipant(house_vote=vote)

            cells = row.find_all("td", recursive=False)
            mp_name = cells[0].a.text.strip()
            riding_name = cells[0].find_all("span", recursive=False)[1].text.strip()[1:-1]
            party_name = cells[1].text.strip()
            recorded_votes = (bool(cells[2].img), bool(cells[3].img), bool(cells[4].img))
            print([mp_name, riding_name, party_name, recorded_votes])

            try:
                modified_mp_name = PARLIAMENTARIAN_MAPPING.get(mp_name, (HONORIFIC.sub("", mp_name)))
                parliamentarian = self.parliamentarian_cache[(modified_mp_name, riding_name)]
            except KeyError:
                parliamentarian = Parliamentarian.objects.filter(
                    names__contains=json.dumps(modified_mp_name)[1:-1],
                    election_candidates__election_riding__riding__slug__contains=slugify(unidecode(riding_name)),
                ).distinct().get()
                self.parliamentarian_cache[(modified_mp_name, riding_name)] = parliamentarian
                # TODO: Add french and english names
                # TODO: Add pop-up link
            hvp.parliamentarian = parliamentarian

            try:
                party = self.party_cache[party_name]
            except KeyError:
                party = Party.objects.get(slug=PARTY_MAPPING[cells[1].text.strip()])
                self.party_cache[party_name] = party
            hvp.party = party

            hvp.recorded_vote = RECORDED_VOTE_MAPPING[recorded_votes]
            hvp.save()

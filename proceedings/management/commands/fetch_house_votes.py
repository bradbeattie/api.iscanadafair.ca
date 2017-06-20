from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak, get_french_parl_url, dateparse, one_or_none, soup_to_text, get_cached_obj, get_cached_dict
from parliaments.models import Session, Parliamentarian, Party, Riding
from proceedings import models
from tqdm import tqdm
from urllib.parse import parse_qs, urlparse
from urllib.parse import urljoin
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
    "Green Party": "gp",
}
WIDGET_ID = re.compile(r"/ParlDataWidgets/en/affiliation/([0-9]+)")
RECORDED_VOTE_MAPPING = {
    (False, False, True): models.HouseVoteParticipant.VOTE_PAIRED,
    (False, True, False): models.HouseVoteParticipant.VOTE_NAY,
    (False, True, True): models.HouseVoteParticipant.VOTE_NAY,  # Strange. See http://www.ourcommons.ca/Parliamentarians/en/votes/40/3/37/, Christian Paradis for an example
    (True, False, False): models.HouseVoteParticipant.VOTE_YEA,
    (True, False, True): models.HouseVoteParticipant.VOTE_YEA,  # Strange. See http://www.ourcommons.ca/Parliamentarians/en/votes/40/3/160/, Paule Brunelle for an example
    (True, True, False): models.HouseVoteParticipant.VOTE_ABSTAINED,
}
PARLIAMENTARIAN_MAPPING = {
    ("Candice Hoeppner", "manitoba-portage-lisgar"): "bergen-candice",
    ("David A. Anderson", "british-columbia-victoria"): "anderson-david-1",
    ("David Anderson", "british-columbia-victoria"): "anderson-david-1",
    ("David Anderson", "saskatchewan-cypress-hills-grasslands"): "anderson-david-2",
    ("David Chatters", "alberta-westlock-st-paul"): "chatters-david-cameron",
    ("Don H. Bell", "british-columbia-north-vancouver"): "bell-don",
    ("Gary Ralph Schellenberger", "ontario-perth-wellington"): "schellenberger-gary",
    ("Glen Douglas Pearson", "ontario-london-north-centre"): "pearson-glen",
    ("Greg Francis Thompson", "new-brunswick-new-brunswick-southwest"): "thompson-gregory-francis",
    ("Gurbax S. Malhi", "ontario-bramalea-gore-malton"): "malhi-gurbax-singh",
    ("Jean C. Lapierre", "quebec-outremont"): "lapierre-jean-c",
    ("John Cummins", "british-columbia-delta-richmond-east"): "cummins-john-martin",
    ("Joseph Volpe", "ontario-eglinton-lawrence"): "volpe-giuseppe-joseph",
    ("Judy A. Sgro", "ontario-humber-river-black-creek"): "sgro-judy",
    ("Judy A. Sgro", "ontario-york-west"): "sgro-judy",
    ("Khristinn Kellie Leitch", "ontario-simcoe-grey"): "leitch-k-kellie",
    ("Megan Anissa Leslie", "nova-scotia-halifax"): "leslie-megan",
    ("Robert D. Nault", "ontario-kenora"): "nault-robert-daniel",
    ("Ruben John Efford", "newfoundland-and-labrador-avalon"): "efford-ruben-john",
    ("Senator Josée Verner", "quebec-louis-saint-laurent"): "verner-josee",
    ("Senator Norman E. Doyle", "newfoundland-and-labrador-st-johns-east"): "doyle-norman-e",
}


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        self.cached_parliamentarians = get_cached_dict(Parliamentarian.objects.filter(election_candidates__election_riding__date__year__gte=2000))
        self.cached_ridings = get_cached_dict(Riding.objects.filter(election_ridings__date__year__gte=2000))
        self.cached_parties = get_cached_dict(Party.objects.all())
        self.cached_parties.update({
            "Independent": [None],
            "Conservative Independent": [None],
            "Independent Conservative": [None],
        })

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
            BeautifulSoup(fetch_url(session.links[EN][sources.NAME_HOC_VOTES[EN]]), "lxml"),
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
                fetch_url(vote.links[lang][sources.NAME_HOC_VOTE_DETAILS[lang]], sometimes_refetch=False),
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
        # TODO: This has been temporarily written to scrape off of HTML
        #       as the new XML format omits party affiliation.
        for row in soup[EN].select("#parlimant > tbody > tr"):  # Note the source code misspells "parliament"
            self.fetch_vote_participant(row, vote, soup)

    def fetch_vote_participant(self, row, vote, soup):
        hvp = models.HouseVoteParticipant(house_vote=vote)
        cells = row.find_all("td", recursive=False)
        mp_link = {EN: cells[0].a}
        mp_name = {EN: mp_link[EN].text.strip()}
        riding_name = cells[0].find_all("span", recursive=False)[1].text.strip()[1:-1]
        party_name = cells[1].text.strip()
        recorded_votes = (bool(cells[2].img), bool(cells[3].img), bool(cells[4].img))

        try:
            without_honorific = HONORIFIC.sub("", mp_name[EN])
            parliamentarian = get_cached_obj(
                self.cached_parliamentarians,
                without_honorific,
            )
        except AssertionError:
            try:
                riding = get_cached_obj(self.cached_ridings, riding_name.replace("—", "--"))
            except AssertionError:
                logger.warning("ERR RIDING {}: {}".format(vote, riding_name))
                return
            try:
                parliamentarian = get_cached_obj(
                    self.cached_parliamentarians,
                    PARLIAMENTARIAN_MAPPING.get((without_honorific, riding.slug)),
                )
            except AssertionError:
                logger.warning("ERR PARLIMENTARIAN {}: {}".format(vote, (without_honorific, riding.slug)))
                return
        if sources.NAME_HOC_VOTES[EN] not in parliamentarian.names[EN]:
            mp_link[FR] = soup[FR].find("a", href=re.compile(r"/ParlDataWidgets/fr/affiliation/{}".format(
                WIDGET_ID.search(cells[0].a.attrs["href"]).groups()[0]
            )))
            mp_name[FR] = mp_link[FR].text.strip()
            for lang in (EN, FR):
                parliamentarian.names[lang][sources.NAME_HOC_VOTES[lang]] = mp_name[lang]
                parliamentarian.links[lang][sources.NAME_HOC_VOTES[lang]] = urljoin(vote.links[lang][sources.NAME_HOC_VOTE_DETAILS[lang]], mp_link[lang].attrs["href"])
            parliamentarian.save()
        hvp.parliamentarian = parliamentarian
        hvp.slug = f"{vote.slug}-{parliamentarian.slug}"

        try:
            party = get_cached_obj(self.cached_parties, PARTY_MAPPING.get(party_name, party_name))
            hvp.party = party
        except AssertionError:
            logger.warning("ERR PARTY {}".format(party_name))
            return

        try:
            hvp.recorded_vote = RECORDED_VOTE_MAPPING[recorded_votes]
        except KeyError:
            logger.warning("ERR VOTE {} {}: {}".format(vote, mp_name, recorded_votes))
            return
        hvp.save()

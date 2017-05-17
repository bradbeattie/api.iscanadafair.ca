from bs4 import BeautifulSoup
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from elections import models
from elections.management.commands.fetch_election_ridings import LOP_ROW_RIDING
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak, one_or_none, dateparse, REVERSE_ORDINAL
from parliaments.models import Parliament
from tqdm import tqdm
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    general_election_data = defaultdict(dict)

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        pending_parliaments = Parliament.objects.filter(Q(general_election__isnull=True) | Q(number__gte=Parliament.objects.last().number - 1))
        if pending_parliaments.exists():
            for parliament in tqdm(
                pending_parliaments,
                desc="Fetch By-Elections, LoP",
                unit="by-election",
            ):
                self.fetch_by_elections(parliament)

        parliaments = Parliament.objects.filter(general_election__isnull=True)
        if parliaments.exists():

            # LoP index
            lop_index_end = BeautifulSoup(fetch_url(
                "http://www.lop.parl.gc.ca/parlinfo/Compilations/ElectionsAndRidings/Elections.aspx?Menu=ElectionsRidings-Election",
            ), "html.parser")
            for row in lop_index_end.select("#ctl00_cphContent_grdElections tr"):
                if row.find("td"):
                    title, date = list(row.find_all("td"))
                    election_number = int(REVERSE_ORDINAL.sub(r"\1", title.text.strip().split()[0]))
                    self.general_election_data[election_number]["date"] = dateparse(date.text.strip())

            # Cache Library of Parliament dates
            lop_index_start = BeautifulSoup(fetch_url(
                "http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=G",
            ), "html.parser")
            for option in lop_index_start.select("select[name=genElection] > option"):
                number = int(option.attrs["value"])
                if number:
                    self.general_election_data[number]["date_fuzz"] = dateparse(option.text.split(" - ")[1])

            # Cache Elections Canada populations
            ec_aggregates = BeautifulSoup(fetch_url(
                "http://www.elections.ca/content.aspx?section=ele&dir=turn&document=index&lang=e",
            ), "html.parser")
            for row in ec_aggregates.find("table").find_all("tr", recursive=False):
                date = datetime.strptime(row.find("td").contents[0].split(" - ")[-1].strip(), "%d %B %Y").date()
                election_number = one_or_none(k for k, v in self.general_election_data.items() if v["date"] == date)
                if election_number:
                    cells = row.find_all("td")
                    self.general_election_data[election_number]["population"] = int(cells[1].text.replace(",", ""))
                    self.general_election_data[election_number]["registered"] = int(cells[2].text.replace(",", ""))
                    self.general_election_data[election_number]["ballots_total"] = int(cells[3].text.replace(",", ""))
                    self.general_election_data[election_number]["turnout"] = Decimal(cells[4].contents[0].replace(",", "")) / 100

            # Fetch the parliaments using the cached data
            for parliament in tqdm(
                parliaments,
                desc="Fetch General Elections, LoP",
                unit="general election",
            ):
                self.fetch_general_election(parliament)

    def fetch_general_election(self, parliament):
        logger.debug("Fetching general election, {}".format(parliament))
        url = "http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Search=Gres&genElection={}".format(parliament.number)
        fetch_url(url)
        election = models.GeneralElection(
            number=parliament.number,
            parliament=parliament,
            links={
                EN: {
                    sources.NAME_LOP_GENERAL_ELECTION[EN]: url_tweak(url, update={"Language": sources.LANG_LOP[EN]}),
                    sources.NAME_WIKI[EN]: "https://en.wikipedia.org/wiki/Canadian_federal_election,_{}".format(self.general_election_data[parliament.number]["date"].year),
                },
                FR: {
                    sources.NAME_LOP_GENERAL_ELECTION[FR]: url_tweak(url, update={"Language": sources.LANG_LOP[FR]}),
                    sources.NAME_WIKI[FR]: "https://fr.wikipedia.org/wiki/Élections_fédérales_canadiennes_de_{}".format(self.general_election_data[parliament.number]["date"].year)
                },
            },
            **self.general_election_data[parliament.number],
        )
        election.save()

    def fetch_by_elections(self, parliament):
        logger.debug("Fetching by-elections, {}".format(parliament))
        url = "http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=Bres&genElection={}".format(parliament.number)

        # Caching for later use
        soup = BeautifulSoup(fetch_url(url), "html.parser")

        dates = set()
        for row in soup.select(".rid"):
            dates.add(dateparse(LOP_ROW_RIDING.search(row.text.strip()).groupdict()["date"]))
        for date in dates:
            models.ByElection.objects.get_or_create(
                parliament=parliament,
                date=date,
                links={
                    EN: {sources.NAME_LOP_BY_ELECTION[EN]: url_tweak(url, remove=("genElection", ), update={"byElection": date.strftime("%Y/%m/%d")})},
                    FR: {sources.NAME_LOP_BY_ELECTION[FR]: url_tweak(url, remove=("genElection", ), update={"byElection": date.strftime("%Y/%m/%d"), "Language": sources.LANG_LOP[FR]})},
                },
            )

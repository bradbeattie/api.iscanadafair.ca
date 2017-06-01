from bs4 import BeautifulSoup
from collections import namedtuple
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from elections import models
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak
from parliaments.models import Province, Riding, Parliamentarian, Party
from tqdm import tqdm
from unidecode import unidecode
from urllib.parse import urljoin
import logging
import pyexcel_ods
import re


logger = logging.getLogger(__name__)
LOP_ROW_RIDING = re.compile("^(?P<name>.*) \((?P<date>[0-9]{4}/[0-9]{2}/[0-9]{2})\)$")
RIDING_SLUG_MAPPINGS = {
    "quebec-mont-royal": "quebec-mount-royal",
    "british-columbia-victoria-district": "british-columbia-victoria",
    "quebec-berthier-maskinonge-delanaudiere": "quebec-berthier-maskinonge-de-lanaudiere"
}
PARLIAMENTARIAN_NAME_MAPPINGS = {
    ("SUTHERLAND, Robert Franklin", "ontario-essex-north"): "8cbc312c-ad1a-45b5-ae85-a50e78fa4dd4",
    ("LAFLAMME, J.-Léo-K.", "quebec-montmagny-lislet"): "55e3b186-f829-4b7e-b9be-11d24e278940",
    ("PICARD, Michel", "quebec-montarville"): "f60ef5d8-8e71-4953-bc1b-a8ea4749a18e",
    ("MULCAIR, Thomas", "quebec-outremont"): "551183c2-2f3e-41ba-8660-2d194cf60169",
    ("THAÏ THI LAC, Ève-Mary", "quebec-saint-hyacinthe-bagot"): "6508ce35-554f-4412-88f7-4f2d6cf8b467",
    ("RAE, Bob", "ontario-toronto-centre"): "98af71e6-be2b-40e8-9501-4e5c27ebbbf5",
    ("HALL FINDLAY, Martha", "ontario-willowdale"): "d2c01fb9-ae85-4e9b-9cd3-a04b42725016",
    ("CLARKE, Rob", "saskatchewan-desnethe-missinippi-churchill-river"): "f7462c37-d7ca-4983-9106-f16b855b3c4f",
    ("HODGINS, Adam King", "ontario-middlesex-east"): "6109f7a9-5793-456e-b7e7-f02d6417b525",
    ("ANDERSON, David", "saskatchewan-cypress-hills-grasslands"): "661a3062-86d1-4ba3-9e70-81c866aa2fc3",
}
PARTY_POPUP = re.compile("Party=([0-9]+)")
PopulationRow = namedtuple("PopulationRow", ("population", "registered", "ballots_rejected"))


class Command(BaseCommand):

    cached_provinces = {}
    cached_ridings = {}
    cached_parliamentarians = {}
    cached_parties = {}

    def add_arguments(self, parser):
        parser.add_argument("ods file")

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        populations = pyexcel_ods.get_data(options["ods file"])
        for election in tqdm(
            models.GeneralElection.objects.filter(election_ridings__isnull=True),
            desc="Fetch General Election Ridings, LoP",
            unit="riding",
        ):
            self.fetch_ridings(election, populations.get(str(election.number), None))

        for election in tqdm(
            models.ByElection.objects.filter(election_ridings__isnull=True),
            desc="Fetch By-Election Ridings, LoP",
            unit="riding",
        ):
            self.fetch_ridings(election)

    @transaction.atomic
    def fetch_ridings(self, election, populations=None):
        if populations:
            populations = dict(
                (slugify(unidecode(" ".join(row[0:2]))), PopulationRow(*[int(cell) for cell in row[2:]]))
                for row in populations[1:]
            )

        if isinstance(election, models.GeneralElection):
            url = election.links[EN][sources.NAME_LOP_GENERAL_ELECTION[EN]]
            kwargs = {"general_election": election}
        else:
            url = election.links[EN][sources.NAME_LOP_BY_ELECTION[EN]]
            kwargs = {"by_election": election}
        soup = BeautifulSoup(fetch_url(url), "html.parser")

        province = None
        election_riding = None
        for tr in soup.select("#MainContent table")[0].find_all("tr", recursive=False):
            if tr.select("h5") or tr.select(".pro"):
                if "Parliament" not in tr.text:
                    try:
                        name = tr.text.strip()
                        province = self.cached_provinces[name]
                    except KeyError:
                        province = Province.objects.get(names__contains=name)
                        self.cached_provinces[name] = province

            elif tr.select(".rid"):
                link = tr.find("a")
                slug = slugify("{}-{}".format(province.slug, link.text))
                slug = RIDING_SLUG_MAPPINGS.get(slug, slug)
                try:
                    riding = self.cached_ridings[slug]
                except KeyError:
                    riding = Riding.objects.get(slug=slug)
                    self.fetch_riding(riding, urljoin(url, link.attrs["href"]))
                election_riding = models.ElectionRiding(
                    riding=riding,
                    date=election.date,
                    **kwargs,
                )
                if populations:
                    population_row = populations[riding.slug]
                    election_riding.population = population_row.population
                    election_riding.registered = population_row.registered
                    election_riding.ballots_rejected = population_row.ballots_rejected
                election_riding.save()

            elif "Votes (%)" in tr.text or "Votes\xa0(%)" in tr.text:
                pass  # Header tr

            else:
                cells = tr.find_all("td")
                name = cells[0].text.strip()
                elected = bool(cells[5].find("img"))
                acclaimed = cells[5].text.strip() == "accl."
                ballots = cells[3].text.replace(",", "").strip()
                ballots_percentage = cells[4].text.replace("%", "").strip()

                if elected or acclaimed:
                    try:
                        lop_item_code = PARLIAMENTARIAN_NAME_MAPPINGS[(name, riding.slug)]
                    except KeyError:
                        lop_item_code = sources.LOP_CODE.search(cells[0].find("a").attrs["href"]).group().lower()
                    parliamentarian = Parliamentarian.objects.get(lop_item_code=lop_item_code)
                    for lang in (EN, FR):
                        if name not in parliamentarian.names[lang].values():
                            parliamentarian.names[lang]["{}, {}".format(
                                sources.NAME_LOP_RIDING_HISTORY[lang],
                                election.name(lang),
                            )] = name  # While the name we pull is from the English source, HFER names never differ
                            parliamentarian.save()
                else:
                    parliamentarian = None

                party = self.fetch_party(
                    cells[1].text.strip(),
                    cells[1].a.attrs["href"],
                    election_riding,
                )

                election_candidate = models.ElectionCandidate(
                    election_riding=election_riding,
                    name=name,
                    parliamentarian=parliamentarian,
                    party=party,
                    elected=elected,
                    acclaimed=acclaimed,
                    profession=cells[2].text.strip(),
                    ballots=int(ballots) if ballots else None,
                    ballots_percentage=(Decimal(ballots_percentage) / 100) if ballots_percentage else None,
                )
                election_candidate.save()

    def fetch_riding(self, riding, url):
        for lang in (EN, FR):
            riding.links[lang][sources.NAME_LOP_RIDING_HISTORY[lang]] = url_tweak(url, update={"Language": sources.LANG_LOP[lang]})
            try:
                fetch_url(riding.links[lang][sources.NAME_LOP_RIDING_HISTORY[lang]])
            except Exception as e:
                logger.exception(e)
        riding.save()
        self.cached_ridings[riding.slug] = riding

    def fetch_party(self, name, popup, election_riding):
        if name in ("Unknown", "Ind.", "N/A") or name.startswith("I "):
            return None

        # Some parties share the same name, but are effectively separate
        if name in ("Rhino", "Nrhino"):
            name = "Rhino ({})".format("1" if election_riding.date.year < 2000 else "2")
        elif name == "C.P.":
            name = "C.P. ({})".format("1" if election_riding.date.year < 2000 else "2")
        elif name == "Soc":
            name = "Soc ({})".format("1" if election_riding.date.year < 1930 else "2")

        # Others just slugify ambiguously
        if name == "NCP":
            name = "NCP (1)"
        elif name == "N.C.P.":
            name = "N.C.P. (2)"
        elif name == "BPC":
            name = "BPC (1)"
        elif name == "B.P.C.":
            name = "B.P.C. (2)"

        try:
            party = self.cached_parties[name]
        except KeyError:
            party = Party()
            for lang in (EN, FR):
                popup_soup = BeautifulSoup(fetch_url("http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer-party.asp?lang={}&Party={}".format(
                    sources.LANG_LOP[lang],
                    PARTY_POPUP.search(popup).groups()[0],
                )), "html.parser")
                party.names[lang][sources.NAME_LOP_PARTY_SHORT[lang]] = popup_soup.find_all("td")[0].text.strip()
                party.names[lang][sources.NAME_LOP_RIDING_HISTORY[lang]] = popup_soup.find_all("td")[1].text.strip()
            party.slug = slugify(name)
            party.lop_item_code = None
            party.save()
            self.cached_parties[name] = party
        return party

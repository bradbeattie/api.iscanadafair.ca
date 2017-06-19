from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from elections.models import ElectionCandidate
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak
from parliaments import models
from tqdm import tqdm
from urllib.parse import urljoin
import logging


logger = logging.getLogger(__name__)

# In some cases, LoP's HFER data differs from its Parliament Files. The following
# set specifies where provided mappings are in conflict and theorized incorrect.
NEGATIVE = set([
    ("clab", "Conservateur (1867-1942)"),
    ("clab", "Conservative (1867-1942)"),
    ("cons", "Liberal-Conservative"),
    ("cons", "Libéral-conservateur"),
    ("cons", "Parti progressiste-conservateur"),
    ("cons", "Progressive Conservative Party"),
    ("lab", "Anti-Confederate"),
    ("lab", "Anti-confédéré"),
    ("lib", "Conservateur (1867-1942)"),
    ("lib", "Conservative (1867-1942)"),
    ("lib", "Liberal (Reformer)"),
    ("lib", "Libéral (réformiste)"),
    ("lib-cons", "Conservateur (1867-1942)"),
    ("lib-cons", "Conservative (1867-1942)"),
    ("na-con", "Nationalist"),
    ("na-con", "Nationaliste"),
    ("na-gov", "Conservateur (1867-1942)"),
    ("na-gov", "Conservative (1867-1942)"),
    ("nd", "Parti Crédit Social"),
    ("nd", "Social Credit Party"),
])

# In some cases, a candidate is shown to win in the HFER data, but doesn't
# appear in the corresponding Parliament file. We'll need to skip over these.
BYPASSED = set([
    (2, "Cluxton, William"),
    (6, "Baird, George Frederick"),
])


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        cached_parties = {}
        for parliament in tqdm(
            models.Parliament.objects.all(),
            desc="Augment Parties, LoP",
            unit="parliament",
        ):
            self.augment_parties_by_parliament_file(parliament, cached_parties)

    @transaction.atomic
    def augment_parties_by_parliament_file(self, parliament, cached_parties):
        for lang in (EN, FR):
            url = parliament.links[lang][sources.NAME_LOP_PARLIAMENT[lang]]
            soup = BeautifulSoup(fetch_url(url), "html.parser")
            for row in tqdm(
                soup.select("#ctl00_cphContent_ctl04_repGeneralElection_ctl00_grdMembers tr"),
                desc=str(parliament),
                unit="party",
            ):
                cells = row.find_all("td", recursive=False)
                if cells:
                    if (parliament.number, cells[0].a.text) in BYPASSED:
                        continue

                    parliamentarian_name = sources.WHITESPACE.sub(" ", cells[0].a.text.strip())
                    party_name = sources.WHITESPACE.sub(" ", cells[2].text.strip())
                    if parliament.number == 13:
                        if party_name == "Unionist (Liberal)":
                            party_name = "Unionist (Conservative and Liberal)"
                        elif party_name == "Union (libéral)":
                            party_name = "Union (conservateurs et libéraux)"
                    if party_name.startswith(("Independent", "Indépendant")):
                        continue

                    lop_item_code = sources.LOP_CODE.search(cells[0].a.attrs["href"]).group().lower()
                    election_candidates = ElectionCandidate.objects.filter(
                        election_riding__general_election=parliament.general_election,
                        parliamentarian__lop_item_code=lop_item_code,
                    )
                    party = election_candidates.first().party

                    # https://lop.parl.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=C says
                    # "Some discrepancies in data may appear. Data appearing in the Federal Member Profile (biography)
                    # should be considered the authoritative source." So we might need to change the party noted from HFER
                    # to that detected through the Parliament file.
                    if not party:
                        if party_name in cached_parties:
                            logger.debug("{}, {}, shows HFER as an independent, but now shows up as {}".format(
                                parliament,
                                parliamentarian_name,
                                party_name,
                            ))
                            election_candidates.update(party=cached_parties[party_name])
                    elif (party.slug, party_name) in NEGATIVE:
                        if lang == EN:
                            logger.debug("{}, {}, shows in HFER as {}, but PFile as {}".format(
                                parliament,
                                parliamentarian_name,
                                party.names[lang][sources.NAME_LOP_RIDING_HISTORY[lang]],
                                party_name,
                            ))
                    elif sources.NAME_LOP_PARLIAMENT[lang] not in party.names[lang]:
                        party.names[lang][sources.NAME_LOP_PARLIAMENT[lang]] = party_name
                        if cells[2].a.attrs.get("href", None):
                            party.links[lang][sources.NAME_LOP_PARTY[lang]] = url_tweak(
                                urljoin(url, cells[2].a.attrs["href"]),
                                update={"Section": "All"},
                            )
                        party.save()
                        logger.debug("{}, mapping {} to {} via {}".format(parliament, party.slug, party_name, parliamentarian_name))
                        cached_parties[party_name] = party

                    # https://lop.parl.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=C says
                    # "Some discrepancies in data may appear. Data appearing in the Federal Member Profile (biography)
                    # should be considered the authoritative source." So we might need to change the party noted from HFER
                    # to that detected through the Parliament file.
                    elif party.names[lang][sources.NAME_LOP_PARLIAMENT[lang]] != party_name:
                        logger.debug("{}, {}, shows HFER as {}, known previous in PFile as {}, but now shows up as {}".format(
                            parliament,
                            parliamentarian_name,
                            party.names[lang][sources.NAME_LOP_RIDING_HISTORY[lang]],
                            party.names[lang][sources.NAME_LOP_PARLIAMENT[lang]],
                            party_name,
                        ))
                        election_candidates.update(party=party)

        government_party_name = sources.WHITESPACE.sub(" ", soup.select("#ctl00_cphContent_GoverningPartyData")[0].text.strip())
        parliament.government_party = cached_parties[government_party_name]
        parliament.save()

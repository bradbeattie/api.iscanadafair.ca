from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak, get_cached_dict, get_cached_obj
from parliaments import models
from tqdm import tqdm
from urllib.parse import urljoin
import logging


logger = logging.getLogger(__name__)
LOP_LIST_MAPPING = {
    "Canada Party": "cp-2",
    "Marxist-Leninist Party of Canada": "m-l",
    "Rhinoceros Party of Canada": "rhino-2",
    "Democratic Advancement Party of Canada": "dap",
    "Natural Law Party": "nlp",
    "Party for Accountability, Competency and Transparency": "act",
    "Progressive Conservative Democratic Representative Coalition": None,
    "Coalition progressiste-conservateur représentatif démocratic": None,
}


class Command(BaseCommand):

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        cached_parties = get_cached_dict(models.Party.objects.all())
        list_url = "https://lop.parl.ca/parlinfo/Lists/Party.aspx"
        for lang in (EN, FR):
            for a in tqdm(
                BeautifulSoup(
                    fetch_url(url_tweak(list_url, update={"Language": sources.LANG_LOP[lang]})),
                    "html.parser"
                ).select("td > a"),
                desc="Augment Parties, LoP",
                unit="party",
            ):
                if "_lnkParty_" not in a.attrs.get("id", ""):
                    continue
                url = url_tweak(
                    urljoin(list_url, a.attrs["href"]),
                    update={"Section": "ALL"},
                    remove=("MenuID", "MenuQuery"),
                )
                lop_item_code = sources.LOP_CODE.search(url).group().lower()
                party = models.Party.objects.filter(lop_item_code=lop_item_code).first()
                if not party:
                    name = sources.WHITESPACE.sub(" ", a.text.strip())
                    name = LOP_LIST_MAPPING.get(name, name)
                    if name is None:
                        continue
                    party = get_cached_obj(cached_parties, name)
                party.links[lang][sources.NAME_LOP_PARTY[lang]] = url
                party.names[lang][sources.NAME_LOP_PARTY[lang]] = a.text.strip()
                party.lop_item_code = sources.LOP_CODE.search(url).group().lower()
                soup = BeautifulSoup(fetch_url(url), "html.parser")
                for link in soup.select("#ctl00_cphContent_dataLinks a"):
                    party.links[lang][sources.AVAILABILITY_WARNINGS.sub("", link.text.strip())] = link.attrs["href"]
                party.save()

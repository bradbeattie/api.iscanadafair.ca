from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, get_cached_dict, get_cached_obj
from parliaments import models
from tqdm import tqdm
from urllib.parse import urljoin
import cssutils
import logging
import re


logger = logging.getLogger(__name__)
WIKI_MAPPING = {
    "Animal Protection Party of Canada": "Animal Alliance Environment Voters Party of Canada",
    "Anti-Confederation Party": "Anti-Communist",
    "Bloc populaire": "Bloc populaire canadien",
    "Canada Party": "cp-1",
    "Canada Party (2015)": "cp-2",
    "Communist Party of Canada (Marxist–Leninist)": "Marxist-Leninist Party",
    "Confederation of Regions Party of Canada": "Confederation of Regions Western Party",
    "Conservative Party of Canada (1867–1942)": "Conservative (1867-1942)",
    "Democratic Party of Canada": "Democrat",
    "Democratic Representative Caucus": None,
    "Equal Rights Party (Canada)": "Equal Rights",
    "Labour Party of Canada": "Labour",
    "Liberal-Progressive": "Liberal Progressive",
    "Marijuana Party (Canada)": "Marijuana Party",
    "McCarthyite candidates 1896": "McCarthyite",
    "Parti Nationaliste du Quebec": "Parti Nationaliste du Québec",
    "Parti canadien (1942)": "Parti canadien",
    "Party for Accountability, Competency and Transparency": "Accountability, Competency and Transparency",
    "Progressive Conservative Party of Canada": "Progressive Conservative",
    "Progressive Party of Canada": "Progressive",
    "Progressive-Conservative (candidate)": None,
    "Reconstruction Party of Canada": "Reconstruction Party",
    "Republican Party (Canada)": "Republican",
    "Rhinoceros Party of Canada (1963–1993)": "rhino-1",
    "Rhinoceros Party": "rhino-2",
    "Socialist Labour Party (Canada)": "Socialist Labour",
    "Socialist Party of Canada": "soc-1",
    "Socialist Party of Canada (WSM)": "soc-2",
}


class Command(BaseCommand):

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        cached_parties = get_cached_dict(models.Party.objects.all())
        list_url = "https://en.wikipedia.org/wiki/List_of_federal_political_parties_in_Canada"
        for tr in tqdm(
            BeautifulSoup(
                fetch_url(list_url),
                "html.parser",
            ).select("table.wikitable > tr"),
            desc="Augment Parties, Wikipedia",
            unit="party",
        ):
            if tr.find_all("td", recursive=False):
                for link in tr.find_all("td", recursive=False)[1].find_all("a"):
                    name = link.attrs["title"].strip()
                    name = WIKI_MAPPING.get(name, name)
                    if name is None:
                        continue
                    try:
                        party = get_cached_obj(cached_parties, name)
                    except AssertionError:
                        logger.warning("Wikipedia mentions {}, but we don't have a mapping for it".format(link.attrs["title"].strip()))
                        continue
                    self.augment_party_by_wikipedia(
                        party,
                        urljoin(list_url, link.attrs["href"]),
                        tr.find_all("td", recursive=False)[0].attrs["style"],
                    )
        models.Party.objects.filter(color="").update(color="#666666")

    def augment_party_by_wikipedia(self, party, link_en, style):
        party.color = cssutils.parseStyle(style).background
        party.color = re.sub(r"^#([0-9a-f])([0-9a-f])([0-9a-f])$", r"#\1\1\2\2\3\3", party.color, flags=re.I)
        if party.color == "#DCDCDC":
            party.color = ""
        try:
            party.links[EN][sources.NAME_WIKI[EN]] = link_en
            soup_en = BeautifulSoup(fetch_url(link_en), "html.parser")
            party.names[EN][sources.NAME_WIKI[EN]] = soup_en.select("#firstHeading")[0].text.strip()
            link_fr = soup_en.select(".interwiki-fr a.interlanguage-link-target")[0].attrs["href"]
            party.links[FR][sources.NAME_WIKI[FR]] = link_fr
            soup_fr = BeautifulSoup(fetch_url(link_fr), "html.parser")
            party.names[FR][sources.NAME_WIKI[FR]] = soup_fr.select("#firstHeading")[0].text.strip()
        except IndexError:
            logger.debug("{} doesn't have a French-language equivalent in Wikipedia at the moment".format(party))
        party.save()

from bs4 import BeautifulSoup
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from elections import models
from elections import get_by_name_variant
from elections.utils import fetch_url
from elections.get_by_name_variant import SkippedObject
import cssutils
import logging
import re


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        logger.info("Augment with Wikipedia")
        for parliament in models.Parliament.objects.all():
            logger.info(parliament)
            self.augment_election_wiki(parliament.general_election)
        self.augment_parties_wiki()

    @transaction.atomic
    def augment_parties_wiki(self):
        logger.info("Augmenting parties: Wikipedia")
        wiki_soup = BeautifulSoup(fetch_url(
            "https://en.wikipedia.org/wiki/List_of_federal_political_parties_in_Canada",
            force_load=not settings.DEBUG,
        ), "html.parser")
        for tr in wiki_soup.select("table.wikitable > tr"):
            if tr.find_all("td", recursive=False):
                for link in tr.find_all("td", recursive=False)[1].find_all("a"):
                    try:
                        party = get_by_name_variant.get_party(name=link.attrs["title"], search_name_source="Wikipedia")
                        party.color = cssutils.parseStyle(tr.find_all("td", recursive=False)[0].attrs["style"]).background
                        party.color = re.sub(r"^#([0-9a-f])([0-9a-f])([0-9a-f])$", r"#\1\1\2\2\3\3", party.color, flags=re.I)
                        if party.color == "#DCDCDC":
                            party.color = ""
                        party.links["Wikipedia"] = "https://en.wikipedia.org{}".format(link.attrs["href"])
                        party.save()
                    except SkippedObject:
                        pass
        models.Party.objects.filter(color="").update(color="#666666")

    @transaction.atomic
    def augment_election_wiki(self, election):
        wiki_edit_url = "{}&action=edit".format(election.links["Wikipedia"].replace(
            "https://en.wikipedia.org/wiki/",
            "https://en.wikipedia.org/w/index.php?title=",
        ))
        wiki_soup = BeautifulSoup(fetch_url(
            wiki_edit_url,
            force_load=not settings.DEBUG,
        ), "html.parser")

        # Get the info box
        page_source = wiki_soup.select("#wpTextbox1")[0].text
        infobox_lines = re.search("{{Infobox election\n(.*?)\n}}", page_source, re.S | re.I).groups()[0].splitlines()
        infobox = {}
        infobox["parties"] = []
        for key, value in [
            line[2:].split("=", 1)
            for line in infobox_lines
            if line.startswith("| ")
        ]:
            key = key.strip()
            value = value.strip()
            try:
                party_place = int(key[-1]) - 1
                while len(infobox["parties"]) <= party_place:
                    infobox["parties"].append({})
                infobox["parties"][party_place][key[:-1]] = value
            except ValueError:
                infobox[key] = value
        election.wiki_info_box = infobox
        election.save()

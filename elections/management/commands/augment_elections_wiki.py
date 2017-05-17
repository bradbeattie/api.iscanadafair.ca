from bs4 import BeautifulSoup
from tqdm import tqdm
from django.core.management.base import BaseCommand
from django.db import transaction
from federal_common import sources
from federal_common.sources import EN
from federal_common.utils import fetch_url, url_tweak
from elections import models
import logging
import re


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        for election in tqdm(
            models.GeneralElection.objects.all(),
            desc="Augment Elections, Wikipedia",
            unit="election",
        ):
            self.augment_election_wiki(election)

    def augment_election_wiki(self, election):
        soup = BeautifulSoup(fetch_url(url_tweak(
            election.links[EN][sources.NAME_WIKI[EN]],
            update={"action": "edit"},
        ), use_cache=True), "html.parser")

        # Get the info box
        page_source = soup.select("#wpTextbox1")[0].text
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

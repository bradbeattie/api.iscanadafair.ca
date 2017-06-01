from bs4 import BeautifulSoup
from collections import defaultdict
from django.core.management.base import BaseCommand
from django.db import transaction
from federal_common.sources import EN
from federal_common.utils import fetch_url
from parliaments import models
from tqdm import tqdm
from urllib.parse import urljoin
import cssutils
import logging
import re


logger = logging.getLogger(__name__)
LIST = re.compile(r"^List of [A-Z] postal codes of Canada$")
XNX = re.compile(r"^[A-Z][0-9][A-Z]$")
URL = re.compile(r"^http://www.ourcommons.ca/Parliamentarians/en/members/.*\(([0-9]+)\)$")


class Command(BaseCommand):

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        riding_id_to_riding = {}
        for parliamentarian in models.Parliamentarian.objects.filter(
            election_candidates__election_riding__date__year__gte=2000,
        ).distinct():
            for url in parliamentarian.links[EN].values():
                match = URL.search(url)
                if match:
                    riding_id_to_riding[int(match.groups()[0])] = parliamentarian.riding
                    break

        for riding_id, fsas in self.get_riding_id_to_fsas().items():
            riding = riding_id_to_riding[riding_id]
            riding.postal_code_fsas = sorted(fsas)
            riding.save()

    def get_riding_id_to_fsas(self):
        fsas = set()
        index_url = "https://en.wikipedia.org/wiki/List_of_postal_codes_in_Canada"
        index_all = BeautifulSoup(fetch_url(index_url), "html.parser")
        for link in tqdm(index_all.findAll("a", {"title": LIST})):
            index_letter = BeautifulSoup(fetch_url(urljoin(index_url, link.attrs["href"])), "html.parser")
            for fsa in tqdm(index_letter.findAll("b", text=XNX)):
                if cssutils.parseStyle(fsa.parent.attrs.get("style", "")).color != "#CCC":
                    fsas.add(fsa.text)

        riding_id_to_fsas = defaultdict(set)
        for fsa in tqdm(fsas):
            result = fetch_url("http://www.ourcommons.ca/Parliamentarians/en/FloorPlan/FindMPs?textCriteria={}".format(fsa))
            try:
                result = result.decode()
            except AttributeError:
                pass
            for riding_id in filter(None, result.split(",")):
                riding_id_to_fsas[int(riding_id)].add(fsa)

        return riding_id_to_fsas

from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from federal_common.utils import fetch_url, get_cached_dict, get_cached_obj
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

        fsas = set()
        index_url = "https://en.wikipedia.org/wiki/List_of_postal_codes_in_Canada"
        index_all = BeautifulSoup(fetch_url(index_url), "html.parser")
        for link in tqdm(index_all.findAll("a", {"title": LIST})):
            index_letter = BeautifulSoup(fetch_url(urljoin(index_url, link.attrs["href"])), "html.parser")
            for fsa in tqdm(index_letter.findAll("b", text=XNX)):
                if cssutils.parseStyle(fsa.parent.attrs.get("style", "")).color != "#CCC":
                    fsas.add(fsa.text)

        cached_ridings = get_cached_dict(models.Riding.objects.filter(election_ridings__date__year__gte=2015))
        person_id_to_riding = {}
        for person in BeautifulSoup(
            fetch_url("http://www.ourcommons.ca/Parliamentarians/en/floorplan"),
            "html.parser",
        ).select(".FloorPlanSeat .Person"):
            riding = get_cached_obj(cached_ridings, person.attrs["constituencyname"])
            person_id_to_riding[int(person.attrs["personid"])] = riding
            riding.post_code_fsas = set()

        for fsa in tqdm(fsas):
            result = fetch_url("http://www.ourcommons.ca/Parliamentarians/en/FloorPlan/FindMPs?textCriteria={}".format(fsa))
            try:
                result = result.decode()
            except AttributeError:
                pass
            for person_id in filter(None, result.split(",")):
                try:
                    person_id_to_riding[int(person_id)].post_code_fsas.add(fsa)
                except:
                    logger.warning(f"Person ID {person_id} expected for FSA {fsa}, but that wasn't found in the floorplan")

        for riding in person_id_to_riding.values():
            riding.post_code_fsas = sorted(riding.post_code_fsas)
            riding.save()

from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak, get_cached_dict, get_cached_obj
from parliaments import models
import logging


logger = logging.getLogger(__name__)
EC_MAPPING = {
    "Marxist-Leninist Party of Canada": "m-l",
    "Canada Party": "cp-2",
}


class Command(BaseCommand):

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)
        cached_parties = get_cached_dict(models.Party.objects.all())
        url = "http://www.elections.ca/content.aspx?dir=par&document=index&section=pol"
        for lang in (EN, FR):
            url_lang = url_tweak(url, update={"lang": sources.LANG_EC[lang]})
            ec_soup = BeautifulSoup(fetch_url(url_lang), "html.parser")
            for h3 in ec_soup.select("h3.partytitle"):
                name = h3.text.strip()
                name_short = h3.attrs["id"]
                name = EC_MAPPING.get(name, name)
                try:
                    party = get_cached_obj(cached_parties, name)
                except AssertionError:
                    party = get_cached_obj(cached_parties, name_short)
                party.names[lang][sources.NAME_EC[lang]] = name
                party.names[lang][sources.NAME_EC_SHORT[lang]] = name_short
                party.links[lang][sources.NAME_EC[lang]] = "{}#{}".format(url_lang, name_short)
                party.save()
                cached_parties[name].add(party)
                cached_parties[name_short].add(party)

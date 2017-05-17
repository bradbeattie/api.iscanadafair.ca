from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, url_tweak, get_cached_dict, get_cached_obj, get_french_parl_url
from parliaments import models
from tqdm import tqdm
from unidecode import unidecode
from urllib.parse import parse_qs, urlparse
from urllib.parse import urljoin
import logging


logger = logging.getLogger(__name__)
MAPPED_PARLIAMENTARIANS = {
    ("Alexander Nuttall", "ontario-barrie-springwater-oro-medonte"): "nuttall-alex",
    ("Candice Hoeppner", "manitoba-portage-lisgar"): "bergen-candice",
    ("David Anderson", "british-columbia-victoria"): "anderson-david-1",
    ("David Anderson", "saskatchewan-cypress-hills-grasslands"): "anderson-david-2",
    ("David Chatters", "alberta-westlock-st-paul"): "chatters-david-cameron",
    ("David de Burgh Graham", "quebec-laurentides-labelle"): "graham-david",
    ("Dianne L. Watts", "british-columbia-south-surrey-white-rock"): "watts-dianne",
    ("Gilles Bernier", "new-brunswick-tobique-mactaquac"): "bernier-gilles-2",
    ("Jean-Guy Carignan", "quebec-quebec-est"): "carignan-jean-guy",
    ("John Cummins", "british-columbia-delta-richmond-east"): "cummins-john-martin",
    ("Joseph Volpe", "ontario-eglinton-lawrence"): "volpe-giuseppe-joseph",
    ("Judy A. Sgro", "ontario-humber-river-black-creek"): "sgro-judy",
    ("Michael Savage", "nova-scotia-dartmouth-cole-harbour"): "savage-michael-john",
    ("Rey Pagtakhan", "manitoba-winnipeg-north-st-paul"): "pagtakhan-rey-d",
    ("Richard Harris", "british-columbia-cariboo-prince-george"): "harris-richard-m",
    ("Robert Kitchen", "saskatchewan-souris-moose-mountain"): "kitchen-robert-gordon",
    ("Robert Nault", "ontario-kenora"): "nault-robert-daniel",
    ("Ronald Duhamel", "manitoba-saint-boniface"): "duhamel-ron-j",
    ("Roy Bailey", "saskatchewan-souris-moose-mountain"): "bailey-roy-h",
    ("Ruben Efford", "newfoundland-and-labrador-avalon"): "efford-ruben-john",
    ("T.J. Harvey", "new-brunswick-tobique-mactaquac"): "harvey-thomas-j",
}


class Command(BaseCommand):

    @transaction.atomic
    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        cached_ridings = get_cached_dict(models.Riding.objects.filter(
            Q(election_ridings__general_election__parliament__number__gte=35) |
            Q(election_ridings__by_election__parliament__number__gte=35)
        ))
        cached_parliamentarians = get_cached_dict(models.Parliamentarian.objects.filter(
            Q(election_candidates__election_riding__general_election__parliament__number__gte=35) |
            Q(election_candidates__election_riding__by_election__parliament__number__gte=35)
        ))

        fetched = set()
        list_url = {
            EN: "http://www.ourcommons.ca/Parliamentarians/en/members",
            FR: "http://www.noscommunes.ca/Parliamentarians/fr/members",
        }
        for parl_link in tqdm(
            BeautifulSoup(
                fetch_url(list_url[EN]),
                "html.parser",
            ).select(".refiner-display-parliament a"),
            desc="Augment Parliamentarians, HoC",
            unit="parliament",
        ):
            parliament = models.Parliament.objects.get(
                number=parse_qs(urlparse(parl_link.attrs["href"]).query)["parliament"][0]
            )
            for lang in (EN, FR):
                parliament.links[lang][sources.NAME_HOC_MEMBERS[lang]] = url_tweak(list_url[lang], update={
                    "parliament": parliament.number,
                    "view": "ListAll",
                })
            for last_name in tqdm(
                BeautifulSoup(fetch_url(
                    parliament.links[EN][sources.NAME_HOC_MEMBERS[EN]],
                ), "html.parser").select(".content-primary .last-name"),
                desc=str(parliament),
                unit="parliamentarian",
            ):
                mp_link = last_name.parent
                mp_url = {EN: urljoin(parliament.links[EN][sources.NAME_HOC_MEMBERS[EN]], mp_link.attrs["href"])}
                if mp_url[EN] not in fetched:
                    fetched.add(mp_url[EN])
                    mp_soup = BeautifulSoup(fetch_url(mp_url[EN], use_cache=True), "html.parser")
                    mp_url[FR] = get_french_parl_url(mp_url[EN], mp_soup)

                    riding_slug = slugify(" ".join((
                        mp_soup.select(".province")[0].text,
                        unidecode(mp_soup.select(".constituency")[0].text),
                    )))
                    try:
                        riding_url = {EN: urljoin(list_url[EN], mp_soup.select(".constituency a")[0].attrs["href"])}
                        riding = get_cached_obj(cached_ridings, riding_slug)
                        for lang in (EN, FR):
                            riding_soup = BeautifulSoup(fetch_url(riding_url[lang], use_cache=True), "html.parser")
                            riding.names[lang][sources.NAME_HOC_CONSTITUENCIES[lang]] = riding_soup.select(".profile h2")[0].text
                            riding.links[lang][sources.NAME_HOC_CONSTITUENCIES[lang]] = riding_url[lang]
                            if lang == EN:
                                riding_url[FR] = get_french_parl_url(riding_url[EN], riding_soup)
                        riding.save()
                    except IndexError:
                        pass

                    joined_name = " ".join((
                        mp_link.select(".first-name")[0].text,
                        mp_link.select(".last-name")[0].text,
                    ))
                    parliamentarian = get_cached_obj(
                        cached_parliamentarians,
                        MAPPED_PARLIAMENTARIANS.get((joined_name, riding_slug), joined_name)
                    )

                    for lang in (EN, FR):
                        parliamentarian.names[lang][sources.NAME_HOC_MEMBERS[EN]] = mp_soup.select(".profile h2")[0].text
                        parliamentarian.links[lang][sources.NAME_HOC_MEMBERS[EN]] = mp_url[lang]
                    parliamentarian.save()
                    if mp_soup.select(".profile.header a[href^=mailto:]"):
                        email = mp_soup.select(".profile.header a[href^=mailto:]")[0].attrs["href"][7:]
                        parliamentarian.links[EN]["Email"] = email
                        parliamentarian.links[FR]["Courriel"] = email

                    # These links were brought in from the LoP and we don't need both (HoC is more comprehensive, e.g. Daniel Turp)
                    parliamentarian.links[EN].pop("MP profile", None)
                    parliamentarian.links[FR].pop("Profil de la députée", None)

                    parliamentarian.save()

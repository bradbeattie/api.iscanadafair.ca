from bs4 import BeautifulSoup
from django.db.models import Q
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, get_cached_dict, get_cached_obj
from parliaments import models
from tqdm import tqdm
from urllib.parse import urljoin
import logging


logger = logging.getLogger(__name__)

PROVINCE_MAPPING = {
    "B.C.": "British Columbia",
    "Newfoundland & Labrador": "Newfoundland and Labrador",
    "P.E.I.": "Prince Edward Island",
}
PARLIAMENTARIAN_MAPPING = {
    ("Bobby Morrissey", "prince-edward-island"): "morrissey-robert",
    ("Bradley Trost", "saskatchewan"): "trost-brad",
    ("David Anderson", "british-columbia"): "anderson-david-1",
    ("David Anderson", "saskatchewan"): "anderson-david-2",
    ("Fred Mifflin", "newfoundland-and-labrador"): "mifflin-fred-j",
    ("Gilles Bernier", "new-brunswick"): "bernier-gilles-2",
    ("Gilles Bernier", "quebec"): "bernier-gilles-1",
    ("Guy Arseneault", "new-brunswick"): "arseneault-guy-h",
    ("Jake Hoeppner", "manitoba"): "hoeppner-jake-e",
    ("Marc Serré", "ontario"): "serre-marc-g",
    ("Ovid Jackson", "ontario"): "jackson-ovid-l",
    ("Peter MacKay", "nova-scotia"): "mackay-peter-gordon",
}


class Command(BaseCommand):

    cached_ridings = {}

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)
        self.augment_parliamentarians_open_parliament()

    @transaction.atomic
    def augment_parliamentarians_open_parliament(self):
        cached_provinces = get_cached_dict(models.Province.objects.all())
        cached_parliamentarians = get_cached_dict(models.Parliamentarian.objects.filter(
            Q(election_candidates__election_riding__general_election__parliament__number__gte=35) |
            Q(election_candidates__election_riding__by_election__parliament__number__gte=35)
        ))

        for url in (
            "https://openparliament.ca/politicians/former/",
            "https://openparliament.ca/politicians/",
        ):
            for row in tqdm(
                BeautifulSoup(fetch_url(url), "html.parser").select(".content > .row"),
                desc="Augment Parliamentarians, OpenParliament.ca",
                unit="parliamentarian",
            ):
                columns = row.find_all("div", recursive=False)
                if len(columns) == 2 and columns[0].find("h2") and columns[1].find("a"):
                    province_name = columns[0].find("h2").text.strip()
                    province = get_cached_obj(cached_provinces, PROVINCE_MAPPING.get(province_name, province_name))
                    if sources.NAME_OP[EN] not in province.names[EN]:
                        province.names[EN][sources.NAME_OP[EN]] = province_name
                        province.save()
                    for link in columns[1].select("a[href^=/politicians/]"):
                        if link.attrs["href"] not in ("/politicians/", "/politicians/former/"):
                            self.augment_parliamentarian_open_parliament(get_cached_obj(cached_parliamentarians, PARLIAMENTARIAN_MAPPING.get(
                                (link.text, province.slug),
                                slugify(link.text),
                            )), urljoin(url, link.attrs["href"]))

    def augment_parliamentarian_open_parliament(self, parliamentarian, url):
        soup = BeautifulSoup(fetch_url(url, use_cache=True), "html.parser")
        for lang in (EN, FR):
            parliamentarian.names[lang][sources.NAME_OP[lang]] = soup.find("h1").text
        parliamentarian.links[EN][sources.NAME_OP[EN]] = url
        for link in soup.select("ul.bulleted a"):
            if link.text == "Wikipedia":
                wiki_soup = BeautifulSoup(fetch_url(link.attrs["href"], use_cache=True, allow_redirects=True), "html.parser")
                parliamentarian.links[EN][sources.NAME_WIKI[EN]] = urljoin(link.attrs["href"], wiki_soup.select("#ca-nstab-main a")[0].attrs["href"])
                try:
                    parliamentarian.links[FR][sources.NAME_WIKI[FR]] = wiki_soup.select(".interwiki-fr a.interlanguage-link-target")[0].attrs["href"]
                except:
                    pass
            elif link.text == "Twitter":
                for lang in (EN, FR):
                    parliamentarian.links[lang][sources.NAME_TWITTER[lang]] = link.attrs["href"]
        parliamentarian.save()

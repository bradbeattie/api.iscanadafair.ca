from bs4 import BeautifulSoup
from django.conf import settings
from django.core.management.base import BaseCommand
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, one_or_none
from urllib.parse import urljoin
import logging


logger = logging.getLogger(__name__)


def ensure_trailing_slash(url):
    if url[-1] != "/":
        return "".join((url, "/"))
    else:
        return url


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        url = "http://www.cpac.ca/en/page/1/?s&category=all&person=all&order=newest&type=videos"
        while url:
            soup = BeautifulSoup(fetch_url(url, use_cache=settings.DEBUG), "html.parser")
            for item in soup.select(".vidlist-main__item"):
                self.fetch_item({EN: urljoin(url, item.select("a")[0].attrs["href"])})
            button_next = one_or_none(soup.select("a.latest-slider__next"))
            if button_next:
                url = urljoin(url, button_next.attrs["href"])

    def fetch_item(self, url):
        url[EN] = ensure_trailing_slash(url[EN])
        soup = BeautifulSoup(fetch_url(url[EN], use_cache=settings.DEBUG), "html.parser")
        url[FR] = ensure_trailing_slash(urljoin(url[EN], one_or_none(soup.select("#language-toggle")).attrs["href"]))

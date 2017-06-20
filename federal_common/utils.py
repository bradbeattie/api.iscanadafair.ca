from collections import defaultdict
from datetime import timedelta
from dateutil.parser import parse as dateutil_parse
from django.conf import settings
from django.utils.text import slugify
from django.utils.timezone import make_aware
from federal_common.sources import EN, FR
from time import sleep
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, urljoin, ParseResult
import copy
import hashlib
import logging
import math
import memcache
import os
import random
import re
import requests


logger = logging.getLogger(__name__)
mc = memcache.Client(['127.0.0.1:11211'], debug=0)
DASHER = re.compile(r"[/.:]")
REVERSE_ORDINAL = re.compile("^([0-9]+)st|nd|rd|th$", re.I)
THROTTLE = 1
HTTP_RESPONSE_CODE_CACHE_DAYS = {404: 30}


def one_or_none(l):
    l = list(l)
    assert len(l) in (0, 1)
    return l[0] if l else None


class FetchSuppressed(Exception):
    pass


class FetchFailure(Exception):
    pass


def fetch_url(url, use_cache=True, allow_redirects=False, case_sensitive=False, discard_content=False, sometimes_refetch=True):
    global THROTTLE
    url_hash_cs = hashlib.sha512(url.encode()).hexdigest()
    url_hash_ci = hashlib.sha512(url.lower().encode()).hexdigest()
    url_hash = url_hash_cs if case_sensitive else url_hash_ci
    try:
        os.makedirs(os.path.join("urlcache", url_hash[0:2]))
    except FileExistsError:
        pass
    filename = os.path.join(
        "urlcache",
        url_hash[0:2],
        "--".join((
            slugify(DASHER.sub("-", url))[0:150],
            url_hash[0:8],
        )),
    )

    if any((
        not os.path.exists(filename),
        not use_cache,
        sometimes_refetch and random.uniform(0, 1) > 0.999,
    )):
        if mc.get(url_hash_cs):
            logger.warning("Fetch suppressed due to recent failure: {}".format(url))
            raise FetchSuppressed(url)
        while True:
            try:
                sleep(THROTTLE / 4)
                THROTTLE = max(0.1, math.pow(THROTTLE, 0.9))
                response = requests.get(url, allow_redirects=allow_redirects, headers={
                    "From": settings.ADMINS[0][1],
                    "User-Agent": "https://github.com/bradbeattie/canadian-parlimentarty-data",
                })
                if response.status_code in (200, 301, 302, 500):
                    break
                logger.warning(f"Fetch returned status {response.status_code}")
            except requests.exceptions.ConnectionError as e:
                logger.warning(e)
            THROTTLE = (THROTTLE + 1) * 2
            logger.warning("Refetching {} (throttle {}s)".format(url, THROTTLE / (10 if settings.DEBUG else 1)))
        if response.status_code != 200:
            mc.set(url_hash_cs, True, 86400 * HTTP_RESPONSE_CODE_CACHE_DAYS.get(response.status_code, 2))
            raise FetchFailure(url, response.status_code, response.content)
        try:
            content = response.content.decode("utf8")
        except UnicodeDecodeError:
            content = response.content.decode("latin1")
        open(filename, "w").write(content)
    elif discard_content:
        return
    else:
        content = open(filename).read()
    content = content.replace("""<?xml version="1.0" encoding="UTF-8"?>""", "").strip()
    return content


def daterange(start_date, end_date, inclusive=False):
    for n in range(int((end_date - start_date).days) + (1 if inclusive else 0)):
        yield start_date + timedelta(n)


def url_tweak(url, remove=None, update=None):
    remove = remove or []
    update = update or {}
    parsed = urlparse(url)._asdict()
    query = parse_qs(parsed["query"], keep_blank_values=True)
    assert not set(remove) & set(update.keys()), "Remove and Update are expected to be mutually exclusive"
    query.update(update)
    for k in remove:
        query.pop(k, None)
    parsed["query"] = urlencode(sorted(query.items()), doseq=True)
    return urlunparse(ParseResult(**parsed))


def datetimeparse(s):
    return make_aware(dateutil_parse(s))


def dateparse(s):
    return dateutil_parse(s).date()


def get_cached_dict(qs):
    cached = defaultdict(set)
    for obj in qs:
        for lang in (EN, FR):
            cached[obj.slug].add(obj)
            if hasattr(obj, "lop_item_code"):
                cached[obj.lop_item_code].add(obj)
            for name in obj.names[lang].values():
                cached[name].add(obj)
                if name.count(", ") == 1:
                    renamed = " ".join(reversed(name.split(", ")))
                    cached[renamed].add(obj)
                    cached[slugify(renamed)].add(obj)
    return cached


def get_cached_obj(cached_dict, name):
    objset = cached_dict[name]
    assert len(objset) == 1, "Expected one entry named {}, got {}".format(name, objset)
    return next(iter(objset))


def get_french_parl_url(root_url, soup):
    return urljoin(
        root_url,
        soup(text=re.compile(r"^Français$"))[0].parent.parent.attrs["href"].replace(":80/", "/"),
    )


def soup_to_text(soup):
    new_soup = copy.copy(soup)
    for br in new_soup.find_all("br"):
        br.replace_with("\n")
    return new_soup.get_text().strip()

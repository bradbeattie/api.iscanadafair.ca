from datetime import timedelta
from django.utils.text import slugify
from time import sleep
import memcache
import hashlib
import os
import re
import requests
import math


mc = memcache.Client(['127.0.0.1:11211'], debug=0)
DASHER = re.compile(r"[/.:]")
THROTTLE = 1

def one_or_none(l):
    l = list(l)
    assert len(l) in (0, 1)
    return l[0] if l else None


def fetch_url(url, force_load=False, allow_redirects=False):
    global THROTTLE
    url_hash = hashlib.sha512(url.encode()).hexdigest()
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
    if not os.path.exists(filename) or force_load:
        assert mc.get(url_hash) != True, "We recently failed to fetch {}, so we won't try again for a while".format(url)
        try:
            print("Fetching", url, "(throttle {})".format(THROTTLE))
            while True:
                try:
                    sleep(THROTTLE)
                    THROTTLE = math.pow(THROTTLE, 0.9)
                    response = requests.get(url, allow_redirects=allow_redirects, headers={
                        "From": settings.ADMINS[0][1],
                        "User-Agent": "https://github.com/bradbeattie/canadian-parlimentarty-data",
                    })
                    break
                except requests.exceptions.ConnectionError as e:
                    THROTTLE = max(1, THROTTLE) * 2
                    print(e, "(throttle {})".format(THROTTLE))
            assert response.status_code == 200, response.content
            content = response.content
            with open(filename, "w") as f:
                try:
                    f.write(content.decode("utf8"))
                except UnicodeDecodeError:
                    f.write(content.decode("latin1"))
        except AssertionError:
            mc.set(url_hash, True, 86400 * 3)
            raise
    else:
        content = open(filename).read()
        #os.utime(filename)
    return content



def daterange(start_date, end_date, inclusive=False):
    for n in range(int((end_date - start_date).days) + (1 if inclusive else 0)):
        yield start_date + timedelta(n)

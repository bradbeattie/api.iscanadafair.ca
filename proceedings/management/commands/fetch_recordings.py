from datetime import date, timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, dateparse, datetimeparse
from parliaments.models import Session
from proceedings import models
from tqdm import tqdm
from unidecode import unidecode
import json
import logging
import re


logger = logging.getLogger(__name__)
locations = {}
CACHE_BEFORE = timedelta(days=0 if settings.DEBUG else 90)
ROOM = re.compile(r"(Room|Pièce) ([^,]+), (.*)")
SUFFIX = re.compile(r"[ -]+$")
HOUSE_PUBLICATIONS = "http://www.ourcommons.ca/documentviewer/en/house/latest-sitting"
HOC_SITTING_NO = re.compile(r"^HoC Sitting No. (.*)$")
HOC_QUESTION_PERIOD_NO = re.compile(r"^Question Period for HoC Sitting No. (.*)")
COMMITTEE_CODE = re.compile("^([A-Z][A-Z0-9]+) Meeting")
WHITESPACE = re.compile(r"\s+")
REPLACEMENTS = {
    EN: (
        ("180 Wellington Street", "Wellington Building"),
        ("180 Wellington", "Wellington Building"),
        ("Wellington Building 415", "Wellington Building - 415"),
        ("Center", "Centre"),
        ("Centre Block, Chamber", "Centre Block - Chamber"),
        ("Valour building, 151 Sparks street", "The Valour Building"),
    ),
    FR: (
        ("180, rue Wellington", "Édifice Wellington"),
        ("Centre Block", "Édifice du Centre"),
        ("Committee Audio 112-N - PVAudio02", "Édifice du Centre - 112-N"),
        ("Committee Video 237-C", "Édifice du Centre - 237-C"),
        ("Committee Video 253-D", "Édifice du Centre - 253-D"),
        ("Edifice", "Édifice"),
        ("Édifice de la Bravoure, 151, rue Sparks", "Édifice de la Bravoure"),
        ("Édifice du Centre 2", "Édifice du Centre - 2"),
        ("Édifice du centre", "Édifice du Centre"),
        ("édifice", "Édifice"),
    ),
}
STATUS_MAPPING = {
    "Adjourned": models.Recording.STATUS_ADJOURNED,
    "Cancelled": models.Recording.STATUS_CANCELLED,
    "Not Started": models.Recording.STATUS_NOT_STARTED,
}
CATEGORY_MAPPING = {
    "thumbnail_audio_e_small.jpg": models.Recording.CATEGORY_AUDIO_ONLY,
    "thumbnail_house_e_small.jpg": models.Recording.CATEGORY_TELEVISED,
    "thumbnail_incamera_e_small.jpg": models.Recording.CATEGORY_IN_CAMERA,
    "thumbnail_no_av_e_small.jpg": models.Recording.CATEGORY_NO_BROADCAST,
    "thumbnail_travel_e_small.jpg": models.Recording.CATEGORY_TRAVEL,
    "thumbnail_video_e_small.jpg": models.Recording.CATEGORY_TELEVISED,
}


def standardize_location(location, lang):
    response = location
    response = WHITESPACE.sub(" ", response)
    response = SUFFIX.sub("", response)
    response = ROOM.sub(r"\3 - \2", response)
    for k, v in REPLACEMENTS[lang]:
        response = response.replace(k, v)
    return response


class Command(BaseCommand):

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        year = date.today().year
        for year in tqdm(
            range(date.today().year, date.today().year - 15, -1),
            desc="Fetch Recordings, ParlVu",
            unit="year",
        ):
            self.fetch_year(year)

    def fetch_year(self, year):
        days = [
            dateparse(day)
            for day in json.loads(fetch_url(
                "http://parlvu.parl.gc.ca/XRender/en/api/Data/GetCalendarYearData/{}0101/-1".format(year),
                use_cache=year < 2017,
            ))
        ]
        for day in tqdm(days, desc=str(year), unit="day"):
            self.fetch_day(day)

    @transaction.atomic
    def fetch_day(self, day):
        events = {
            lang: {
                event["Id"]: event
                for event in json.loads(fetch_url(
                    "http://parlvu.parl.gc.ca/XRender/{}/api/Data/GetContentEntityByYMD/{}/-1".format(
                        sources.LANG_PARLVU[lang],
                        day.strftime("%Y%m%d"),
                    ),
                    use_cache=date.today() - day > CACHE_BEFORE,
                ))
            }
            for lang in (EN, FR)
        }
        for event_id, event in events[EN].items():
            event = {EN: event, FR: events[FR][event_id]}
            recording = models.Recording(
                category=CATEGORY_MAPPING[event[EN]["ThumbnailUri"].rsplit("/", 1)[-1]],
                scheduled_start=datetimeparse(event[EN]["ScheduledStart"]),
                scheduled_end=datetimeparse(event[EN]["ScheduledEnd"]),
                actual_start=datetimeparse(event[EN]["ActualStart"]) if event[EN]["ActualStart"] else None,
                actual_end=datetimeparse(event[EN]["ActualEnd"]) if event[EN]["ActualEnd"] else None,
                status=STATUS_MAPPING[event[EN]["EntityStatusDesc"]],
                slug="-".join((str(day), slugify(unidecode(event[EN]["Title"])))),
            )
            for lang in (EN, FR):
                recording.location[lang] = standardize_location(event[lang]["Location"], lang)
                recording.names[lang][sources.NAME_PARLVU_DESCRIPTION[lang]] = event[lang]["Description"]
                recording.names[lang][sources.NAME_PARLVU_TITLE[lang]] = event[lang]["Title"]
                recording.links[lang] = "http://parlvu.parl.gc.ca/XRender/{}/PowerBrowser/PowerBrowserV2/{}/-1/{}".format(
                    sources.LANG_PARLVU[lang],
                    day.strftime("%Y%m%d"),
                    event[EN]["Id"],
                )
            locations.setdefault(recording.location[EN], recording.location[FR])
            assert locations[recording.location[EN]] == recording.location[FR]

            title = recording.names[EN][sources.NAME_PARLVU_TITLE[EN]]
            match = COMMITTEE_CODE.search(title)
            if match:
                code = match.groups()[0]
                session = Session.objects.filter(date_start__lte=day).filter(Q(date_end__gte=day) | Q(date_end__isnull=True)).get()
                prefix = "-".join((code.lower(), session.slug, ""))
                recording.committee = models.Committee.objects.get(Q(slug__startswith=prefix) | Q(slug__startswith=prefix.replace("aano-", "inan-").replace("saan-", "sina-")))

            if recording.status != models.Recording.STATUS_CANCELLED:
                for regex in (HOC_SITTING_NO, HOC_QUESTION_PERIOD_NO):
                    match = regex.search(title)
                    if match:
                        number = "".join(reversed(match.groups()[0].split("-"))).lstrip("0")
                        sitting_number = models.Sitting.objects.filter(date__gt=day - timedelta(days=120), date__lt=day + timedelta(days=120), number=number).first()
                        sitting_day = models.Sitting.objects.filter(date=day).first()
                        if sitting_day and sitting_day.number == number:
                            recording.sitting = sitting_day
                        elif day < date.today():
                            logger.warning("ParlVU speaks of [{} ({})]({}), but OurCommons thinks {} and {}.".format(
                                title,
                                day,
                                recording.links[EN],
                                "[#{} is on {}]({})".format(
                                    sitting_day.number,
                                    sitting_day.date,
                                    list(sitting_day.links[EN].values())[0]
                                ) if sitting_day else "no session exists on this date".format(day),
                                "[#{} is on {}]({})".format(
                                    sitting_number.number,
                                    sitting_number.date,
                                    list(sitting_number.links[EN].values())[0],
                                ) if sitting_number else "#{} doesn't exist".format(number),
                            ))

                recording.save()

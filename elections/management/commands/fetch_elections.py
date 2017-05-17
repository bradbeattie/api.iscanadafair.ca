from bs4 import BeautifulSoup
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from elections import get_by_name_variant
from elections import models
from elections.utils import fetch_url, one_or_none
import inflect
import logging
import os
import re
import requests


logger = logging.getLogger(__name__)
inflector = inflect.engine()
ORDINAL_REGEX = re.compile(r"(st|nd|rd|th)\b")
IGNORED_PARTIES = ("Unknown", "Ind.", "N/A")


class Command(BaseCommand):

    riding_profiles = {}
    parliamentarian_profiles = {}
    named_parliamentarian_profiles = defaultdict(list)

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        logger.info("Fetch elections")
        self.fetch_elections()
        for parliament in models.Parliament.objects.all():
            logger.info(parliament)
            self.fetch_ridings(parliament.general_election)
            self.fetch_parliament_details(parliament)
        self.fetch_byelections()

    @transaction.atomic
    def fetch_elections(self):
        logger.info("Fetching general elections and associated parliaments")
        cached_data = defaultdict(dict)

        # EC index
        lop_index_start = BeautifulSoup(fetch_url(
            "http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=G",
            force_load=not settings.DEBUG,
        ), "html.parser")
        for option in lop_index_start.select("select[name=genElection] > option"):
            if " - " in option.text:
                cached_data[int(option.attrs["value"])]["election"] = {
                    "date_start": datetime.strptime(option.text.split(" - ")[1], "%Y/%m/%d").date(),
                    "links": {},
                }

        # LoP index
        lop_index_end = BeautifulSoup(fetch_url(
            "http://www.lop.parl.gc.ca/parlinfo/Compilations/ElectionsAndRidings/Elections.aspx?Menu=ElectionsRidings-Election",
            force_load=not settings.DEBUG,
        ), "html.parser")
        for row in lop_index_end.select("#ctl00_cphContent_grdElections tr"):
            if row.find("td"):
                parliament, date_end = list(row.find_all("td"))
                election_number = int(ORDINAL_REGEX.sub("", parliament.text.strip().split()[0]))
                cached_data[election_number]["election"]["date_end"] = datetime.strptime(date_end.text.strip(), "%Y.%m.%d").date()
                cached_data[election_number]["parliament"] = {
                    "links": {
                        "Library of Parliament": "{}&Section=ALL".format(row.find("a").attrs["href"].replace("../..", "http://www.lop.parl.gc.ca/parlinfo")),
                        "Wikipedia": "https://en.wikipedia.org/wiki/{}_Canadian_Parliament".format(inflector.ordinal(election_number)),
                    },
                }

        # Augment additionally with population, registered voters, ballots cast, and voter turnout
        ec_aggregates = BeautifulSoup(fetch_url(
            "http://www.elections.ca/content.aspx?section=ele&dir=turn&document=index&lang=e",
            force_load=not settings.DEBUG,
        ), "html.parser")
        for row in ec_aggregates.find("table").find_all("tr", recursive=False):
            date_end = datetime.strptime(row.find("td").contents[0].split(" - ")[-1].strip(), "%d %B %Y").date()
            election_number = one_or_none(k for k, v in cached_data.items() if v["election"]["date_end"] == date_end)
            if election_number:
                cells = row.find_all("td")
                cached_data[election_number]["election"]["population"] = int(cells[1].text.replace(",", ""))
                cached_data[election_number]["election"]["registered"] = int(cells[2].text.replace(",", ""))
                cached_data[election_number]["election"]["ballots_total"] = int(cells[3].text.replace(",", ""))
                cached_data[election_number]["election"]["turnout"] = Decimal(cells[4].contents[0].replace(",", "")) / 100
                cached_data[election_number]["election"]["links"].update({
                    "Library of Parliament": "http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=Gres&genElection={}".format(election_number),
                    "Wikipedia": "https://en.wikipedia.org/wiki/Canadian_federal_election,_{}".format(date_end.year),
                })

        # Create associated parliaments
        for election_number, election_cached_data in cached_data.items():
            parliament, created = models.Parliament.objects.get_or_create(
                number=election_number,
                defaults=election_cached_data["parliament"],
                seats=0,  # To be populated during fetch_parliament_details
            )
            general_election, created = models.GeneralElection.objects.get_or_create(
                number=election_number,
                parliament=parliament,
                defaults=election_cached_data["election"],
            )

    def fetch_byelections(self):
        logger.info("Fetching by-elections")
        lop_soup = BeautifulSoup(fetch_url(
            "http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=B",
            force_load=not settings.DEBUG,
        ), "html.parser")
        for option in reversed(lop_soup.select("select[name=byElection] > option")):
            if option.text != "--By-Election--":
                by_election_date = datetime.strptime(option.text, "%Y/%m/%d").date()
                self.fetch_ridings(
                    election=None,
                    lop_url="http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=Bres&byElection={}".format(option.text),
                    description="By Election ({})".format(by_election_date),
                    election_riding_kwargs={
                        "date": by_election_date,
                        "by_election_parliament": models.GeneralElection.objects.filter(date_end__lt=by_election_date).order_by("-date_end").first().parliament,
                    },
                )

    @transaction.atomic
    def fetch_parliament_details(self, parliament):
        lop_soup = BeautifulSoup(fetch_url(parliament.links["Library of Parliament"]), "html.parser")
        parliament.seats = models.ElectionRiding.objects.filter(general_election__parliament=parliament).distinct().count()
        parliament.government_party = get_by_name_variant.get_party(
            name=lop_soup.select("#ctl00_cphContent_GoverningPartyData")[0].text,
            search_name_source="Library of Parliament, Parliament Details",
        )
        parliament.government_party.save()
        parliament.save()
        for row in lop_soup.select("#ctl00_cphContent_ctl00_grdSessionList tr"):
            if row.attrs["class"] != ["GridHeader"]:
                cells = row.find_all("td")
                date_start = cells[1].text.split(" - ")[0].strip()
                date_end = cells[1].text.split(" - ")[1].strip()
                models.Session.objects.get_or_create(
                    parliament=parliament,
                    number=int(ORDINAL_REGEX.sub("", cells[0].text)),
                    defaults={
                        "number": int(ORDINAL_REGEX.sub("", cells[0].text)),
                        "date_start": datetime.strptime(date_start, "%Y.%m.%d").date(),
                        "date_end": datetime.strptime(date_end, "%Y.%m.%d").date() if date_end else None,
                        "sittings_senate": int(cells[3].text),
                        "sittings_house": int(cells[4].text),
                    },
                )

    # TODO: This function has grown a touch large. Needs refactoring.
    @transaction.atomic
    def fetch_ridings(self, election, lop_url=None, election_riding_kwargs=None, description=None):
        if election:
            lop_url = "http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer.asp?Language=E&Search=Gres&genElection={}&ridProvince=0&submit1=Search".format(election.number)
            election_riding_kwargs = {"general_election": election, "date": election.date_end}
            description = str(election)

        lop_soup = BeautifulSoup(fetch_url(lop_url), "html.parser")
        province = None
        riding = None
        for tr in lop_soup.select("#MainContent table")[0].find_all("tr", recursive=False):
            if tr.select("h5") or tr.select(".pro"):
                if "Parliament" not in tr.text:
                    province, created = models.Province.objects.get_or_create(
                        name=tr.text.strip(),
                        defaults={},
                    )
            elif tr.select(".rid"):
                link = tr.find("a")
                try:
                    riding = self.riding_profiles[(province.name, slugify(link.text))]
                except KeyError:
                    riding = models.Riding(
                        name=link.text,
                        province=province,
                    )
                    riding.save()
                    self.riding_profiles[(province.name, slugify(link.text))] = riding
                profile_url = "http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/{}".format(link.attrs["href"])
                if profile_url not in riding.links.values():
                    riding.links["Library of Parliament, {}".format(election)] = profile_url
                riding.save()
                election_riding = models.ElectionRiding(
                    riding=riding,
                    **election_riding_kwargs,
                )
                election_riding.save()
            elif "Votes (%)" in tr.text:
                pass  # Header tr
            else:
                cells = tr.find_all("td")
                name = cells[0].text.strip()
                elected = bool(cells[5].find("img"))
                acclaimed = cells[5].text.strip() == "accl."

                if elected or acclaimed:
                    try:
                        lop_profile_url = "http://www.lop.parl.gc.ca{}&MoreInfo=True&Section=All".format(cells[0].find("a").attrs["href"])
                    except AttributeError:
                        lop_profile_url = None

                    # LoP messes up some names and links. I've contacted them for fixes.
                    if name == "THAÏ THI LAC, Ève-Mary":
                        name = "THI LAC, Ève-Mary Thaï"
                    if name == "THI LAC, Ève-Mary Thaï":
                        lop_profile_url = "http://www.lop.parl.gc.ca/ParlInfo/Files/Parliamentarian.aspx?Item=6508ce35-554f-4412-88f7-4f2d6cf8b467&Language=E&MoreInfo=True&Section=ALL"
                    if lop_profile_url and name == "BACHAND, André" and election.number == 40:
                        lop_profile_url = "http://www.lop.parl.gc.ca/parlinfo/Files/Parliamentarian.aspx?Item=a1bf1700-34a1-4d48-a5a7-bea4d0a251e8&Language=E&MoreInfo=True&Section=All"
                    if lop_profile_url and name == "ANDERSON, David" and election.number == 42:
                        lop_profile_url = "http://www.lop.parl.gc.ca/parlinfo/Files/Parliamentarian.aspx?Item=661A3062-86D1-4BA3-9E70-81C866AA2FC3&Language=E&MoreInfo=True&Section=All"
                    if not lop_profile_url and name == "PICARD, Michel" and election.number == 42:
                        lop_profile_url = "http://www.lop.parl.gc.ca/parlinfo/Files/Parliamentarian.aspx?Item=f60ef5d8-8e71-4953-bc1b-a8ea4749a18e&Language=E&MoreInfo=True&Section=ALL"
                    if name == "SUTHERLAND, Robert Franklin" and election.number in (9, 10):
                        lop_profile_url = "http://www.lop.parl.gc.ca/ParlInfo/Files/Parliamentarian.aspx?Item=8cbc312c-ad1a-45b5-ae85-a50e78fa4dd4&Language=E&MoreInfo=True&Section=ALL"
                    if name == "LAFLAMME, J.-Léo-K." and election.number == 19:
                        lop_profile_url = "http://www.lop.parl.gc.ca/ParlInfo/Files/Parliamentarian.aspx?Item=55e3b186-f829-4b7e-b9be-11d24e278940&Language=E&MoreInfo=True&Section=ALL"

                    # Some winning candidates aren't linked, but should be
                    if not lop_profile_url:
                        lop_profile_url = get_by_name_variant.get_parliamentarian(
                            name=name,
                            search_name_source="Library of Parliament",
                            election_candidates__election_riding__riding__province=province,
                        ).links["Library of Parliament, Profile"]
                    if not lop_profile_url:
                        raise Exception("Unlinked winning candidate", name, lop_url)

                    slugged_name = slugify(name)
                    if lop_profile_url not in self.named_parliamentarian_profiles[slugged_name]:
                        self.named_parliamentarian_profiles[slugged_name].append(lop_profile_url)
                    name_count = self.named_parliamentarian_profiles[slugged_name].index(lop_profile_url)
                    if name_count:
                        name += " ({})".format(name_count + 1)

                    if lop_profile_url.lower() in self.parliamentarian_profiles:
                        parliamentarian = self.parliamentarian_profiles[lop_profile_url.lower()]
                        if name != parliamentarian.name and name not in parliamentarian.name_variants.values():
                            parliamentarian.name_variants["Library of Parliament, {}".format(description)] = name
                            parliamentarian.save()

                    else:
                        parliamentarian = models.Parliamentarian(name=name)
                        parliamentarian.links["Library of Parliament, Profile"] = lop_profile_url
                        self.parliamentarian_profiles[lop_profile_url.lower()] = parliamentarian
                        try:
                            parliamentarian_soup = BeautifulSoup(fetch_url(parliamentarian.links["Library of Parliament, Profile"]), "html.parser")
                            parliamentarian.name_variants["Library of Parliament, Profile"] = parliamentarian_soup.select("#ctl00_cphContent_lblTitle")[0].text
                            try:
                                parliamentarian.birthtext = parliamentarian_soup.select("#ctl00_cphContent_DateOfBirthData")[0].text.strip().replace(".", "-")
                                parliamentarian.birthdate = datetime.strptime(parliamentarian.birthtext, "%Y-%m-%d").date()
                            except:
                                pass

                            for link in parliamentarian_soup.select("#ctl00_cphContent_dataLinks a"):
                                parliamentarian.links[link.text] = link.attrs["href"]

                            # Download the parliamentarian's photo if they have one
                            photo_url = "http://www.lop.parl.gc.ca/parlinfo/{}".format(
                                parliamentarian_soup.select("#ctl00_cphContent_imgParliamentarianPicture")[0].attrs["src"].replace("../", "")
                            )
                            if "00000000-0000-0000-0000-000000000000" not in photo_url:
                                parliamentarian.links["Library of Parliament, Photo"] = photo_url
                                filename = "{}.jpg".format(photo_url.rsplit("=", 1)[-1])
                                filepath = parliamentarian.photo.field.upload_to(None, filename)
                                if os.path.exists(os.path.join(settings.MEDIA_ROOT, filepath)):
                                    parliamentarian.photo = filepath
                                else:
                                    parliamentarian.photo.save(filename, ContentFile(requests.get(photo_url).content))
                        except (AssertionError, IndexError) as e:
                            print("\tPROFILE ERROR", description, parliamentarian.name, e)
                        parliamentarian.save()
                else:
                    parliamentarian = None

                party_name = cells[1].text.strip()
                if party_name in IGNORED_PARTIES:
                    party = None
                else:
                    # LoP labels the Reform party differently between by-elections and general elections
                    if party_name == "R":
                        party_name = "Ref."

                    # Oddly, the LoP assocaites two candidates in the 1960s with the Reform party
                    if party_name == "Ref." and election_riding.date.year < 1970:
                        party_name = None

                    # Several candidates were mislabelled as Republican, but were probaby Rhino
                    # TODO: Not sure if any were legitimately part of a Republican party. Worth looking into?
                    if party_name == "RP":
                        party_name = None

                    # There were two Rhino parties
                    if party_name in ("Rhino", "Nrhino"):
                        party_name = "Rhino ({})".format("1" if election_riding.date.year < 2000 else "2")

                    # There were two Canada parties
                    if party_name == "C.P.":
                        party_name = "C.P. ({})".format("1" if election_riding.date.year < 2000 else "2")

                    # There were two Socialist parties
                    if party_name == "Soc":
                        party_name = "Soc ({})".format("1" if election_riding.date.year < 1930 else "2")

                    if party_name:
                        party, created = models.Party.objects.get_or_create(name=party_name)
                        if "Library of Parliament, Election Popup" not in party.name_variants:
                            party_soup = BeautifulSoup(fetch_url(
                                "http://www.lop.parl.gc.ca/About/Parliament/FederalRidingsHistory/hfer-party.asp?lang=E&Party={}".format(
                                    re.search("Party=([0-9]+)", cells[1].find("a").attrs["href"]).groups()[0],
                                )
                            ), "html.parser")
                            if party.name == "Rhino" and name == "RIVARD, Lucien":
                                pass  # This candidate is incorrectly reported on the LoP
                            party.name_variants["Library of Parliament, Election Popup"] = party_soup.find_all("td")[1].text.strip()
                            party.save()

                ballots = cells[3].text.replace(",", "").strip()
                ballots_percentage = cells[4].text.replace("%", "").strip()
                ec, created = models.ElectionCandidate.objects.get_or_create(
                    name=name,
                    election_riding=election_riding,
                    defaults={
                        "parliamentarian": parliamentarian,
                        "party": party,
                        "profession": cells[2].text.strip(),
                        "ballots": int(ballots) if ballots else None,
                        "ballots_percentage": (Decimal(ballots_percentage) / 100) if ballots_percentage else None,
                        "elected": elected,
                        "acclaimed": acclaimed,
                    },
                )
                if (ec.elected or ec.acclaimed) and not tr.find("a"):
                    raise Exception("No link?", ec)

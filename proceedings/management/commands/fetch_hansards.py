from collections import namedtuple, defaultdict
from datetime import datetime, time, timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from federal_common import sources
from federal_common.sources import EN, FR, WHITESPACE
from federal_common.utils import fetch_url, one_or_none, get_cached_dict, get_cached_obj
from lxml import etree
from lxml.etree import _ProcessingInstruction, _ElementUnicodeResult
from parliaments.models import Parliamentarian
from proceedings import models
from tqdm import tqdm
import logging
import pytz
import re


logger = logging.getLogger(__name__)
TZ = pytz.timezone(settings.TIME_ZONE)
CONTENT_MAY_DIFFER = (

    # French version often uses <Sup/> or <I/> for text formatting that the English version does not
    "Affiliation",
    "DivisionNumber",
    "OrderOfBusinessTitle",
    "ParaText",
    "ProceduralText",
    "QuestionID",
    "ResponseContent",
    "SubjectOfBusinessQualifier",
    "SubjectOfBusinessTitle",
    "title",

    # Content may be identical, but ordering is alphabetical per language
    "MemberList",
    "AppendixTitle",
    "Content",

    # The contents are all actually one, but line broken differently per language
    "MemberListsTitle",

    # A fair number of French XML files are missing their MetaVolumeNumber
    "ExtractedInformation",
)
KNOWN_ISSUES = (
    "39-2-75",   # FR: SubjectOfBusiness 2408815 missing qualifier, has ProceduralText in its place
    "40-2-85",   # FR: SubjectOfBusinessQualifier missing in SubjectOfBusiness 2870025
    "40-2-86",   # FR: Timestamp missing from SubjectOfBusiness 2870249
    "40-3-113",  # EN: Questioner just before ParaText 2235455 is missing Affiliation
    "40-3-120",  # EN: Responder missing after ParaText 2289451
    "40-3-149",  # FR: SubjectOfBusiness 3828366 missing SubjectOfBusinessQualifier
    "40-3-67",   # FR: SubjectOfBusiness 3275652 missing SubjectOfBusinessQualifier
    "40-3-89",   # FR: SubjectOfBusiness 3435036 missing SubjectOfBusinessContent
    "41-1-15",   # EN: Responder missing after ParaText 2469467
    "41-1-23",   # FR: SubjectOfBusinessQualifer missing in SubjectOfBusiness 4307039
    "41-2-233",  # FR: SubjectOfBusinessTitle missing in SubjectOfBusiness 8754777
    "41-1-269",  # EN: SubjectOfBusiness 8079738 missing SubjectOfBusinessQualifier
    "41-2-68",   # FR: Missing a FloorLanguage tag
    "41-2-120",  # EN: Missing a FloorLanguage tag
)
PARSED = "element-already-parsed"
SAID_PREFIX = re.compile(r"^(He|She) said: ")  # TODO: USE THIS
Rendering = namedtuple("Rendering", ("tag", "content"))
HtmlMapping = namedtuple("Rendering", ("wrapper", "joiner"))
HTML_MAPPING = {
    "B": HtmlMapping("strong", ""),
    "CommitteeQuote": HtmlMapping("blockquote", ""),
    "I": HtmlMapping("em", ""),
    "LegislationQuote": HtmlMapping("blockquote", ""),
    "Line": HtmlMapping("span", "<br />"),
    "ParaText": HtmlMapping("p", ""),
    "Poetry": HtmlMapping("div", ""),
    "ProceduralText": HtmlMapping("p", ""),
    "Quote": HtmlMapping("blockquote", ""),
    "QuotePara": HtmlMapping("p", ""),
    "Representing": HtmlMapping("p", ""),
    "Sub": HtmlMapping("sub", ""),
    "Subtitle": HtmlMapping("span", "<br />"),
    "Sup": HtmlMapping("sup", ""),
    "Verse": HtmlMapping("p", ""),
    "title": HtmlMapping("span", ""),
}
CACHED_PARLIAMENTARIANS = get_cached_dict(Parliamentarian.objects.filter(Q(birthtext__gte="1900") | Q(birthtext="")))
HONORIFICS = r"(?P<honorific>Mr|M|Ms|Mrs|Miss|Hon|Right Hon|L'hon)\.?"
SPEAKER_FORMATS = [
    re.compile(r"^{} (?P<name>[^()]*)(?P<suffix> .*)?$".format(HONORIFICS)),
    re.compile(r"^(The Acting Speaker|The Presiding Officer|The Assistant Deputy Speaker) \({} (?P<name>[^()]*)\)$".format(HONORIFICS)),
]
MAPPED_PARLIAMENTARIANS_BY_NAME = {
    "Candice Hoeppner": "bergen-candice",
    "Daniel Hays": "hays-daniel",
    "David Chatters": "chatters-david-cameron",
    "Francis Valeriote": "valeriote-frank",
    "George Furey": "furey-george-j",
    "Harold Glenn Albrecht": "albrecht-harold",
    "Jean-Guy Carignan": "carignan-jean-guy",
    "Jeffrey Watson": "watson-jeff",
    "John Cummins": "cummins-john-martin",
    "Joseph Volpe": "volpe-giuseppe-joseph",
    "Judy A. Sgro": "sgro-judy",
    "Khristinn Kellie Leitch": "leitch-k-kellie",
    "Mervin Tweed": "tweed-mervin-c",
    "Michael Savage": "savage-michael-john",
    "Norman Doyle": "doyle-norman-e",
    "Noël A. Kinsella": "kinsella-noel-a",
    "Noël Kinsella": "kinsella-noel-a",
    "Rey Pagtakhan": "pagtakhan-rey-d",
    "Richard Harris": "harris-richard-m",
    "Robert Clarke": "clarke-bob",
    "Robert Nault": "nault-robert-daniel",
    "Roy Bailey": "bailey-roy-h",
}
MAPPED_PARLIAMENTARIANS_BY_TITLE = {
    "Chief Patrick Brazeau (National Chief of the Congress of Aboriginal Peoples)": "brazeau-patrick",
    "Hon. David Anderson (Minister of the Environment, Lib.)": "anderson-david-1",
    "Hon. David Anderson (Victoria, Lib.)": "anderson-david-1",
    "Mr. André Bachand (Richmond—Arthabaska, PC)": "bachand-andre-2",
    "Mr. David Anderson (Cypress Hills—Grasslands, CPC)": "anderson-david-2",
    "Mr. David Anderson (Parliamentary Secretary (for the Canadian Wheat Board) to the Minister of Agriculture and Agri-Food and Minister for the Canadian Wheat Board, CPC)": "anderson-david-2",
    "Mr. David Anderson (Parliamentary Secretary to the Minister for the Canadian Wheat Board, CPC)": "anderson-david-2",
    "Mr. David Anderson (Parliamentary Secretary to the Minister of Agriculture and Agri-Food and Minister for the Canadian Wheat Board (Canadian Wheat Board), CPC)": "anderson-david-2",
    "Mr. David Anderson (Parliamentary Secretary to the Minister of Foreign Affairs and Consular, CPC)": "anderson-david-2",
    "Mr. David Anderson (Parliamentary Secretary to the Minister of Foreign Affairs, CPC)": "anderson-david-2",
    "Mr. David Anderson (Parliamentary Secretary to the Minister of Natural Resources and for the Canadian Wheat Board, CPC)": "anderson-david-2",
    "Mr. Kilger": "kilger-robert-bob",
    "Mr. Mario Beaulieu (La Pointe-de-l'Île, BQ)": "beaulieu-mario-2",
    "Mr. Martin (Winnipeg Centre)": "martin-pat",
    "Mr. Milliken": "milliken-peter-andrew-stewart",
    "Ms. Catterall": "catterall-marlene",
    "The Acting Speaker (Mr. Bélair)": "belair-reginald",
    "The Acting Speaker (Mr. Proulx)": "proulx-marcel",
    "The Acting Speaker (Ms. Bakopanos)": "bakopanos-eleni",
}
UNMAPPED_NAMES = {
    "H. E. Vicente Fox Quesada (President of the United Mexican States)",
    "H.E. Felipe Calderón Hinojosa (President of the United Mexican States)",
    "H.E. Mr. François Hollande (President of the French Republic)",
    "H.E. Petro Poroshenko (President of Ukraine)",
    "H.H. Aga Khan (49th Hereditary Imam of the Shia Imami Ismaili Muslims)",
    "His Excellency Hamid Karzai (President of the Islamic Republic of Afghanistan)",
    "His Excellency Victor Yushchenko (President of Ukraine)",
    "Hon. John Howard (Prime Minister of Australia)",
    "Le Président",
    "Le vice-président",
    "Mr. Barclay D. Howden (Director General, Directorate of Nuclear Cycle and Facilities Regulation)",
    "Mr. Barclay D. Howden",
    "Mr. Brian McGee (Senior Vice President and Chief Nuclear Officer)",
    "Mr. Brian McGee",
    "Mr. Clem Chartier (President of the Métis National Council)",
    "Mr. Daniel Meneley (Former Chief Engineer of AECL)",
    "Mr. Daniel Meneley",
    "Ms. Beverley Jacobs (President of the Native Women’s Association of Canada)",
    "Ms. Mary Simon (President Inuit Tapiriit Kanatami)",
    "Chief Phil Fontaine (National Chief of the Assembly of First Nations)",
    "Mr. David F. Torgerson (Executive Vice President and Chief Technology Officer and President for the Research and Technology Division AECL)",
    "Mr. David F. Torgerson",
    "Mr. Robert Strickert (Former manager of Pickering and Site VP of Darlington)",
    "Ms. Linda J. Keen (President and Chief Executive Officer, Canadian Nuclear Safety Commission)",
    "Ms. Linda J. Keen",
    "Right Hon. David Cameron (Prime Minister of the United Kingdom of Great Britain and Northern Ireland)",
    "The Acting Speaker",
    "The Assistant Deputy Chair",
    "The Assistant Deputy Chairman",
    "The Chair",
    "The Chairman",
    "The Clerk of the House",
    "The Deputy Chair",
    "The Deputy Speaker",
    "The Speaker",
}


def normalize_whitespace(content):
    if isinstance(content, str):
        return WHITESPACE.sub(" ", content).strip()
    else:
        return {
            lang: normalize_whitespace(string)
            for lang, string in content.items()
        }


def strip_empty_elements(element):
    if isinstance(element, _ElementUnicodeResult):
        return "TEXT"

    for child in element.xpath("child::node()"):
        strip_empty_elements(child)

    if isinstance(element, _ProcessingInstruction):
        element.getparent().remove(element)
    elif not len(element):
        if (element.text is None or not element.text.strip()) and element.tag != "Affiliation":
            element.getparent().remove(element)


def get_child_structure(element, include_text_nodes=False, depth=1):
    if isinstance(element, _ElementUnicodeResult):
        return "TEXT" if element.strip() else None
    elif not depth:
        return element.tag
    elif include_text_nodes:
        return [
            element.tag,
            element.attrib.get("id", None),
            list(filter(None, [
                get_child_structure(child, include_text_nodes=include_text_nodes, depth=depth - 1)
                for child in element.xpath("child::node()")
            ]))
        ]
    else:
        return [
            element.tag,
            element.attrib.get("id", None),
            [
                get_child_structure(child, include_text_nodes=include_text_nodes, depth=depth - 1)
                for child in element
            ]
        ]


def assert_child_structure(element):
    child_structure = "".join(map(lambda x: f"{{{x}}}", get_child_structure(element)))
    expected = COMPILED_STRUCTURE.get(element.tag, LEAF)
    assert expected.search(child_structure), f"{element.tag} expected {expected} but got {child_structure}"


class Command(BaseCommand):

    tree = None
    floor_language = None
    timestamp = None
    hansard_block = None
    hansard_block_number = None
    sitting = None

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        for sitting in tqdm(
            models.Sitting.objects.filter(links__contains=sources.NAME_HOC_HANSARD_XML[EN]),
            desc="Fetch Hansards, HoC",
            unit="sitting",
        ):
            try:
                self.fetch_hansard(sitting)
                print()
                print(sitting, sitting.links[EN][sources.NAME_HOC_HANSARD_XML[EN]])
            except:
                print()
                print(sitting, sitting.links[EN][sources.NAME_HOC_HANSARD_XML[EN]])
                raise

    @transaction.atomic
    def fetch_hansard(self, sitting):

        # Fetch and parse the hansard XML
        self.tree = {
            lang: etree.ElementTree(etree.fromstring(fetch_url(
                sitting.links[lang][sources.NAME_HOC_HANSARD_XML[lang]],
            ).replace("""<?xml version="1.0" encoding="UTF-8"?>\n""", "")))
            for lang in (EN, FR)
        }

        # Strip out empty elements
        for lang in (EN, FR):
            strip_empty_elements(self.tree[lang].getroot())

        # If the structure checks out, parse down from the root
        self.hansard_block_number = 0
        self.sitting = sitting
        self.parse(self.tree[EN].getroot())

    def get_french_element(self, el_en):
        el_fr = one_or_none(self.tree[FR].xpath(self.tree[EN].getpath(el_en)))
        # assert get_child_structure(el_en.getparent()) == get_child_structure(el_fr.getparent())
        return el_fr

    def get_child_responses(self, element, selected_lang):
        response = defaultdict(list)
        for child in element.xpath("child::node()"):
            parsed = self.parse(child, selected_lang)
            for lang, content in parsed.items():
                response[lang].append(content)
        return dict(response)

    def new_hansard_block(self):
        assert self.hansard_block is None, "Opening a hansard block while one is already open?"
        self.hansard_block_number += 1
        self.hansard_block = models.HansardBlock(
            sitting=self.sitting,
            number=self.hansard_block_number,
            slug="{}-{}".format(self.sitting.slug, self.hansard_block_number),
            start_approx=datetime.combine(self.sitting.date, time(0), TZ) + timedelta(  # We use a timedelta here instead as some timestamps push us into hour 24 (e.g. http://www.noscommunes.ca/Content/House/412/Debates/097/HAN097-E.XML)
                hours=self.timestamp[0],
                minutes=self.timestamp[1],
            ),
            metadata={EN: {}, FR: {}},
        )

    def save_hansard_block(self):
        assert self.hansard_block is not None, "Saving a hansard block before opening a new one?"
        self.hansard_block.save()
        self.hansard_block = None

    def parse(self, element, lang=None):
        # print("PARSE", element, element.getparent())

        #
        if element is None:
            return {}
        if isinstance(element, _ElementUnicodeResult):
            return self.parse_text_node(element, lang)

        # Don't allow an element to be processed twice.
        #
        # We prevent this such that some tags may pre-process their child
        # elements which may be used in the creation of HansardBlocks later
        # on. For example, SubjectOfBusiness tags should first process
        # their SubjectOfBusinessTitle so that included Intervention tags
        # know which SubjectOfBusiness title relates to them.
        if element.attrib.get(PARSED, None) is not None:
            return {}
        else:
            element.attrib[PARSED] = "True"

        # Parse the element opening
        parse_open = getattr(self, f"{element.tag.lower()}_open", None)
        if parse_open:
            shortcut_response = parse_open(element, lang)
            if shortcut_response is not None:
                return shortcut_response

        # Recurse down into the children
        if lang is None and element.tag in CONTENT_MAY_DIFFER:
            child_responses = self.get_child_responses(element, EN)
            try:
                french_element = self.get_french_element(element)
                french_element.attrib[PARSED] = "True"
                child_responses.update(self.get_child_responses(french_element, FR))
            except:
                # Error handling to account for the same problem as self.parse_text_node
                pass
        else:
            child_responses = self.get_child_responses(element, lang)

        # Parse the element closing
        parse_close_func = getattr(self, f"{element.tag.lower()}_close", None)
        parse_close_response = parse_close_func(element, lang, child_responses) if parse_close_func else None
        if parse_close_response is not None:
            return parse_close_response
        elif element.tag in HTML_MAPPING:
            return {
                lang: """<{html_tag} class="{tag}">{joined_content}</{html_tag}>""".format(
                    html_tag=HTML_MAPPING[element.tag].wrapper,
                    tag=element.tag.lower(),
                    joined_content=HTML_MAPPING[element.tag].joiner.join(content).strip(),
                )
                for lang, content in child_responses.items()
            }
        elif any((
            element.tag not in PATTERN_STRUCTURE,
            PATTERN_STRUCTURE.get(element.tag, None) == TITLE_TEXT,
            element.tag in ("Affiliation", "PersonSpeaking"),
        )):
            return {
                lang: "".join(content)
                for lang, content in child_responses.items()
            }
        else:
            return self.unparsed(element, lang, child_responses)

    def memberlists_open(self, element, lang):
        return {}

    def documenttitle_open(self, element, lang):
        return {}

    def extractedinformation_open(self, element, lang):
        # TODO: Do we want to do anything with this subtree? Maybe create a HansardBlock to open the session?
        return {}

    def timestamp_open(self, element, lang):
        self.timestamp = (int(element.attrib["Hr"]), int(element.attrib["Mn"]))
        return {}

    def floorlanguage_open(self, element, lang):
        self.floor_language = element.attrib["language"]
        return {}

    def paratext_close(self, element, lang, child_responses):
        if len(element) == 1 and element.find("Quote") is not None:
            return {
                lang: "".join(content).strip()
                for lang, content in child_responses.items()
            }

    def personspeaking_open(self, element, lang):
        return normalize_whitespace({
            lang: content
            for lang, content in self.parse(element.find("Affiliation"), lang).items()
        })

    def questioner_open(self, *args):
        return self.personspeaking_open(*args)

    def responder_open(self, *args):
        return self.personspeaking_open(*args)

    def divisiontype_open(self, element, lang):
        self.division_type = self.parse(element.find("Type"), lang)
        self.division_title = self.parse(element.find("Title"), lang)
        self.division_nil = self.parse(element.find("Nil"), lang)
        self.division_total = self.parse(element.find("Total"), lang)

    def divisiontype_close(self, element, lang, child_responses):
        response = {
            lang: """
                <h4>{division_type}{division_title}</h4>
                <ul class="divisiontype-affiliations">{affiliations}{division_nil}</ul>
            """.format(
                division_type=self.division_type[lang],
                division_title=self.division_title[lang] if self.division_title else "",
                affiliations="".join("""<li>{}</li>""".format(child) for child in content),
                division_nil="".join("""<li class="nil">{}</li>""".format(child) for child in self.division_nil[lang]) if self.division_nil else "",
            ).strip()
            for lang, content in child_responses.items()
        }
        self.division_type = None
        self.division_title = None
        self.division_total = None
        self.division_nil = None
        return response

    def division_open(self, element, lang):
        self.new_hansard_block()
        self.division_number = self.parse(element.find("DivisionNumber"), lang)

    def division_close(self, element, lang, child_responses):
        self.hansard_block.content = {
            lang: """<h3 class="division">{division_number}</h3>{content}""".format(
                division_number=self.division_number[lang],
                content="\n".join(content),
            )
            for lang, content in child_responses.items()
        }
        # self.hansard_block.parliamentarian=None  # TODO: Use self.person_speaking to populate this
        self.hansard_block.category = models.HansardBlock.CATEGORY_DIVISION
        self.save_hansard_block()
        self.division_number = None
        return {}

    def writtenquestionresponse_open(self, element, lang):
        question_id = self.parse(element.find("QuestionID"), lang)
        # questioner = self.parse(element.find("Questioner"), lang)
        question_content = self.parse(element.find("QuestionContent"), lang)
        self.new_hansard_block()
        self.hansard_block.content = {
            lang: """<h3 class="questionid">{question_id}</h3>{content}""".format(
                question_id=question_id[lang] if question_id else "",
                content=content,
            )
            for lang, content in question_content.items()
        }
        # TODO: ASSOCIATE PARLIAMENTARIAN
        self.hansard_block.category = models.HansardBlock.CATEGORY_WRITTEN_QUESTION
        self.save_hansard_block()

        if element.find("ResponseContent") is not None:
            # responder = self.parse(element.find("Responder"), lang)
            response_content = self.parse(element.find("ResponseContent"), lang)
            self.new_hansard_block()
            self.hansard_block.content = response_content
            # TODO: ASSOCIATE PARLIAMENTARIAN
            self.hansard_block.category = models.HansardBlock.CATEGORY_WRITTEN_RESPONSE
            self.save_hansard_block()

        return {}

    def committee_open(self, element, lang):
        self.new_hansard_block()
        self.committee_title = self.parse(element.find("title"), lang)

    def committee_close(self, element, lang, child_responses):
        self.hansard_block.content = {
            lang: """<h3>{committee_title}</h3><div class="committeemembergroups">{content}</div>""".format(
                committee_title=self.committee_title.get(lang, ""),
                content="\n".join(content),
            ).strip()
            for lang, content in child_responses.items()
        }
        self.hansard_block.category = models.HansardBlock.CATEGORY_COMMITTEE
        self.save_hansard_block()
        self.committee_title = None
        return {}

    def committeemembergroup_open(self, element, lang):
        self.committeemembergroup_title = self.parse(element.find("title"), lang)
        self.committeemembergroup_representing = self.parse(element.find("Representing"), lang)
        self.committeemembergroup_total = self.parse(element.find("Total"), lang)

    def committeemembergroup_close(self, element, lang, child_responses):
        response = {
            lang: """
                <h4>{committeemembergroup_title}{committeemembergroup_representing}</h4>
                <ul class="committeemembergroup-affiliations">{affiliations}</ul>
                {committeemembergroup_total}
            """.format(
                committeemembergroup_title=self.committeemembergroup_title.get(lang, ""),
                committeemembergroup_representing=self.committeemembergroup_representing.get(lang, ""),
                committeemembergroup_total=self.committeemembergroup_total.get(lang, ""),
                affiliations="".join("""<li>{}</li>""".format(child) for child in content),
            ).strip()
            for lang, content in child_responses.items()
        }
        self.committeemembergroup_title = None
        self.committeemembergroup_representing = None
        self.committeemembergroup_total = None
        return response

    def memberlist_open(self, element, lang):
        self.new_hansard_block()
        self.memberlist_title = self.parse(element.find("title"), lang)
        self.memberlist_subtitle = self.parse(element.find("Subtitle"), lang)
        self.memberlist_labelline = self.parse(element.find("LabelLine"), lang)
        self.memberlist_note = self.parse(element.find("Note"), lang)

    def memberlist_close(self, element, lang, child_responses):
        self.hansard_block.content = {
            lang: """
                <h3>{memberlist_title}{memberlist_subtitle}{memberlist_labelline}</h3>
                {memberlist_note}
                <ul class="memberlist-members">{content}</ul>
            """.format(
                memberlist_title=self.memberlist_title.get(lang, ""),
                memberlist_subtitle=self.memberlist_subtitle.get(lang, ""),
                memberlist_labelline=self.memberlist_labelline.get(lang, ""),
                memberlist_note=self.memberlist_note.get(lang, ""),
                content="\n".join("""<li>{}</li>""".format(member) for member in content),
            ).strip()
            for lang, content in child_responses.items()
        }
        self.hansard_block.category = models.HansardBlock.CATEGORY_MEMBERLIST
        self.save_hansard_block()
        self.memberlist_title = None
        self.memberlist_subtitle = None
        self.memberlist_labelline = None
        self.memberlist_note = None
        return {}

    def subjectofbusiness_open(self, element, lang):
        self.subject_of_business = list(map(lambda x: (x, self.parse(x, lang)), filter(lambda x: x is not None, (
            element.find(tag)
            for tag in ("SubjectOfBusinessTitle", "SubjectOfBusinessQualifier", "CatchLine")
        ))))

    def subjectofbusiness_close(self, element, lang, child_responses):
        self.subject_of_business = None
        return {}

    def subjectofbusinesscontent_open(self, element, lang):
        self.get_child_responses(element, lang)
        # TODO: AND THEN DO WHAT WITH THEM?
        for child in element.xpath("child::node()"):
            parsed = self.parse(child, lang)
            if parsed:
                print("SoB", child, parsed)
        return {}

    def orderofbusiness_open(self, element, lang):
        self.order_of_business = list(map(lambda x: self.parse(x, lang), filter(lambda x: x is not None, (
            element.find(tag)
            for tag in ("OrderOfBusinessTitle", "CatchLine")
        ))))

    def orderofbusiness_close(self, element, lang, child_responses):
        self.order_of_business = None
        return {}

    def intervention_open(self, element, lang):
        self.new_hansard_block()
        self.intervention_type = element.attrib.get("Type", None)
        self.set_person_speaking(element, lang)

    def set_person_speaking(self, element, lang):
        self.person_speaking = normalize_whitespace(self.parse(element.find("PersonSpeaking"), lang) or {
            EN: element.attrib["ToCText"],
            FR: self.get_french_element(element).attrib["ToCText"],
        })
        self.parliamentarian_speaking = None
        if self.person_speaking[EN] not in UNMAPPED_NAMES:
            try:
                self.parliamentarian_speaking = get_cached_obj(
                    CACHED_PARLIAMENTARIANS,
                    element.find("PersonSpeaking").find("Affiliation").attrib["DbId"]
                )
            except:
                try:
                    self.parliamentarian_speaking = get_cached_obj(
                        CACHED_PARLIAMENTARIANS,
                        MAPPED_PARLIAMENTARIANS_BY_TITLE[self.person_speaking[EN]]
                    )
                except KeyError:
                    for speaker_format in SPEAKER_FORMATS:
                        match = speaker_format.search(self.person_speaking[EN])
                        if match:
                            try:
                                name = normalize_whitespace(match.groupdict()["name"])
                                self.parliamentarian_speaking = get_cached_obj(
                                    CACHED_PARLIAMENTARIANS,
                                    MAPPED_PARLIAMENTARIANS_BY_NAME.get(name, name),
                                )
                            except AssertionError:
                                print("UNMATCHED SPEAKER", self.sitting, [self.person_speaking[EN], match.groupdict()["name"].strip()])
                            break
                    else:
                        print("SPEAKER FORMAT MISMATCH", self.sitting, [self.person_speaking[EN]])
                if self.parliamentarian_speaking:
                    try:
                        CACHED_PARLIAMENTARIANS[element.find("PersonSpeaking").find("Affiliation").attrib["DbId"]].add(
                            self.parliamentarian_speaking
                        )
                    except:
                        pass

    def intervention_close(self, element, lang, child_responses):
        # TODO: Augment the intervention with SoB and OoB
        self.hansard_block.content = {
            lang: "\n".join(content)
            for lang, content in child_responses.items()
        }
        self.hansard_block.parliamentarian = self.parliamentarian_speaking
        self.hansard_block.category = models.HansardBlock.CATEGORY_INTERVENTION
        self.save_hansard_block()
        self.intervention_type = None
        self.person_speaking = None
        self.parliamentarian_speaking = None
        return {}

    def content_close(self, element, lang, child_responses):
        return {
            lang: """<div class="{tag}">{content}</div>""".format(
                tag=element.tag.lower(),
                content="\n".join(content),
            )
            for lang, content in child_responses.items()
        }

    def questioncontent_close(self, *args):
        return self.content_close(*args)

    def responsecontent_close(self, *args):
        return self.content_close(*args)

    def hansardbody_close(self, *args):
        return {}

    def prayer_open(self, *args):
        return {}

    def intro_close(self, *args):
        return {}

    def hansard_close(self, *args):
        return {}

    def parse_text_node(self, element, lang):
        if not element.strip():
            response = {}
        elif lang:
            response = {lang: str(element)}
        else:
            try:
                response = {
                    EN: WHITESPACE.sub(" ", str(element)),
                    FR: WHITESPACE.sub(" ", str(self.get_french_element(element.getparent()).text)),
                }
            except AttributeError:
                # In some odd cases, the two hansards don't match up. Consider the example
                # of http://www.noscommunes.ca/Content/House/402/Debates/085/HAN085-E.XML
                # and its French counterpart. <SubjectOfBusiness id="2870025"> is qualified
                # in English as "Health", but unqualified in French. I've contacted
                # infohoc@parl.gc.ca to see about having this fixed.
                response = {
                    EN: WHITESPACE.sub(" ", str(element)),
                }
        return normalize_whitespace(response)

    def unparsed(self, element, lang, child_responses):
        print("\nUNPARSED ELEMENT", lang, element.tag, element.attrib.get("id", None))
        print("  PATTERN STRUCTURE:", PATTERN_STRUCTURE.get(element.tag, None))
        for lang, content in child_responses.items():
            print(f"  CHILD CONTENT[{lang}]:", "<JOIN>".join(content))
        print()
        if not lang:
            return {
                EN: f"<{element.tag}>",
                FR: f"<{element.tag}>",
            }
        else:
            return {
                lang: f"<{element.tag}>",
            }


RICH_TEXT = "({})*".format("|".join(map(lambda x: f"{{{x}}}", (
    "Affiliation",
    "B",
    "CommitteeQuote",
    "Document",
    "I",
    "Insertion",
    "LegislationQuote",
    "Poetry",
    "Query",
    "Quote",
    "Sub",
    "Sup",
))))
IDENTITY_TEXT = "{Affiliation}({Affiliation})?"
TITLE_TEXT = "({Sup}|{I}|{B}|{Query})*"
LINE_TEXT = "({Line})+"
PATTERN_STRUCTURE = {
    "Affiliation": "({Role}|{Name}|{Constituency}|{Province}|{Party})*",
    "AffiliationGroup": "{title}{Total}({Affiliation})+",
    "Appendix": "{AppendixLabel}({AppendixTitle})?{AppendixContent}",
    "AppendixContent": "({ParaText}|{Intervention})+",
    "AppendixTitle": LINE_TEXT,
    "B": TITLE_TEXT,
    "CatchLine": TITLE_TEXT,
    "Committee": "{title}({CommitteeMemberGroup})+",
    "CommitteeGroup": "{title}({Committee})+",
    "CommitteeMemberGroup": "({title})?({Representing})?({Affiliation})+({Total})?",
    "CommitteeQuote": "{QuotePara}",
    "Content": "({ParaText}|{Motion})+",
    "Division": "{DivisionNumber}({DivisionType})+",
    "DivisionNumber": TITLE_TEXT,
    "DivisionType": "{Type}({Title})?(({Affiliation})+|{Nil})({Total})?",
    "Document": TITLE_TEXT,
    "DocumentTitle": "{DocumentName}",
    "ExtractedInformation": "({ExtractedItem})+",
    "ExtractedItem": TITLE_TEXT,
    "FloorLanguage": "{I}",
    "Hansard": "{StartPageNumber}{DocumentTitle}{ExtractedInformation}({Corrigendum})?{HansardBody}({MemberLists})?",
    "HansardBody": "({Intro})?({OrderOfBusiness})*({Appendix})*",
    "I": TITLE_TEXT,
    "Insertion": TITLE_TEXT,
    "Intervention": "({PersonSpeaking})?({Content})?",
    "Intro": "{ParaText}({Prayer})?({Intervention})*({SubjectOfBusiness})*",
    "LabelLine": "{Name}{Constituency}({Province})?{Party}",
    "LegislationQuote": "{QuotePara}",
    "Line": TITLE_TEXT,
    "MemberList": "{title}({Subtitle})?({LabelLine})?({Affiliation}|{AffiliationGroup}|{Committee}|{CommitteeGroup})*({Note})?",
    "MemberLists": "{MemberListsLabel}{MemberListsTitle}({MemberList})+",
    "MemberListsTitle": LINE_TEXT,
    "Motion": "{MotionBody}",
    "MotionBody": "({ParaText})+",
    "OrderOfBusiness": "({OrderOfBusinessTitle})?({CatchLine})?({SubjectOfBusiness})+",
    "OrderOfBusinessTitle": TITLE_TEXT,
    "ParaText": RICH_TEXT,
    "PersonSpeaking": IDENTITY_TEXT,
    "Poetry": "({Verse}|{Line})+",
    "ProceduralText": TITLE_TEXT,
    "QuestionContent": "({ParaText})+",
    "QuestionID": TITLE_TEXT,
    "Questioner": IDENTITY_TEXT,
    "Quote": "({QuotePara})+",
    "QuotePara": RICH_TEXT,
    "Representing": LINE_TEXT,
    "Responder": IDENTITY_TEXT,
    "ResponseContent": "({ParaText}|{table})+",
    "Sub": TITLE_TEXT,
    "SubjectOfBusiness": "({SubjectOfBusinessTitle})?({SubjectOfBusinessQualifier})?({CatchLine})?({SubjectOfBusinessContent})?",
    "SubjectOfBusinessContent": "({Intervention}|{Division}|{WrittenQuestionResponse}|{ParaText}|{ThroneSpeech})*",
    "SubjectOfBusinessQualifier": TITLE_TEXT,
    "SubjectOfBusinessTitle": TITLE_TEXT,
    "Subtitle": TITLE_TEXT,
    "Sup": TITLE_TEXT,
    "ThroneSpeech": "{ThroneSpeechPara}",
    "ThroneSpeechPara": LINE_TEXT,
    "Verse": LINE_TEXT,
    "WrittenQuestionResponse": "({QuestionID})?({Questioner})?{QuestionContent}({Responder})?({ResponseContent})?",
    "table": "({title})?{tgroup}",
    "tgroup": "{tbody}",
    "tbody": "({row})+",
    "row": "({entry})+",
}
COMPILED_STRUCTURE = {
    k: re.compile(f"^{v}$")
    for k, v in PATTERN_STRUCTURE.items()
}
LEAF = re.compile("^$")

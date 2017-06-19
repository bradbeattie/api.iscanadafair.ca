from collections import namedtuple, defaultdict
from copy import copy
from django.utils.timezone import make_aware
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from federal_common import sources
from federal_common.sources import EN, FR, WHITESPACE
from federal_common.utils import fetch_url, one_or_none, get_cached_dict, get_cached_obj, datetimeparse
from lxml import etree
from lxml.etree import _ProcessingInstruction, _ElementUnicodeResult
from parliaments.models import Parliamentarian
from proceedings import models
from tqdm import tqdm
import logging
import re


logger = logging.getLogger(__name__)


# Tags where the subtree structures may differ between French and English (sometimes erroneously)
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


# Tags that automatically save and clear the hansard block cache upon entering and exiting during a depth-first-search
BoundaryCategories = namedtuple("BoundaryCategories", ("open_outer", "open_inner", "close_inner", "close_outer"))
BOUNDARY_CATEGORIES = {
    "Appendix": BoundaryCategories(None, models.HansardBlock.CATEGORY_ASIDES, models.HansardBlock.CATEGORY_ASIDES, None),
    "AppendixContent": BoundaryCategories(None, models.HansardBlock.CATEGORY_ASIDES, models.HansardBlock.CATEGORY_ASIDES, None),
    "Division": BoundaryCategories(None, models.HansardBlock.CATEGORY_DIVISION, models.HansardBlock.CATEGORY_DIVISION, None),
    "Hansard": BoundaryCategories(None, models.HansardBlock.CATEGORY_UNEXPECTED, models.HansardBlock.CATEGORY_UNEXPECTED, None),
    "HansardBody": BoundaryCategories(None, models.HansardBlock.CATEGORY_UNEXPECTED, models.HansardBlock.CATEGORY_UNEXPECTED, None),
    "Intervention": BoundaryCategories(models.HansardBlock.CATEGORY_ASIDES, models.HansardBlock.CATEGORY_INTERVENTION, models.HansardBlock.CATEGORY_INTERVENTION, models.HansardBlock.CATEGORY_ASIDES),
    "Intro": BoundaryCategories(None, models.HansardBlock.CATEGORY_ASIDES, models.HansardBlock.CATEGORY_ASIDES, None),
    "MemberList": BoundaryCategories(None, models.HansardBlock.CATEGORY_MEMBERLIST, models.HansardBlock.CATEGORY_MEMBERLIST, None),
    "MemberLists": BoundaryCategories(None, models.HansardBlock.CATEGORY_UNEXPECTED, models.HansardBlock.CATEGORY_UNEXPECTED, None),
    "OrderOfBusiness": BoundaryCategories(None, models.HansardBlock.CATEGORY_UNEXPECTED, models.HansardBlock.CATEGORY_UNEXPECTED, None),
    "QuestionContent": BoundaryCategories(None, None, models.HansardBlock.CATEGORY_WRITTEN_QUESTION, None),
    "Responder": BoundaryCategories(None, models.HansardBlock.CATEGORY_WRITTEN_RESPONSE, None, None),
    "ResponseContent": BoundaryCategories(None, None, models.HansardBlock.CATEGORY_WRITTEN_RESPONSE, None),
    "SubjectOfBusiness": BoundaryCategories(None, models.HansardBlock.CATEGORY_ASIDES, models.HansardBlock.CATEGORY_ASIDES, None),
    "SubjectOfBusinessContent": BoundaryCategories(None, None, models.HansardBlock.CATEGORY_ASIDES, None),
    "WrittenQuestionResponse": BoundaryCategories(models.HansardBlock.CATEGORY_ASIDES, models.HansardBlock.CATEGORY_WRITTEN_QUESTION, models.HansardBlock.CATEGORY_UNEXPECTED, None),
}
NotBoundary = BoundaryCategories(None, None, None, None)
METADATA_TAGS = {
    "AppendixLabel",
    "AppendixTitle",
    "CatchLine",
    "DivisionNumber",
    "LabelLine",
    "MemberListsLabel",
    "MemberListsTitle",
    "Nil",
    "Note",
    "OrderOfBusinessTitle",
    "QuestionID",
    "SubjectOfBusinessQualifier",
    "SubjectOfBusinessTitle",
    "Title",
    "Total",
    "Type",
}
TAGS_THAT_KEEP_METADATA_ON_CLOSING = {
}
SUBJECTOFBUSINESS_METADATA = set([
    "OrderOfBusiness-CatchLine",
    "OrderOfBusiness-OrderOfBusinessTitle",
    "OrderOfBusiness-Rubric",
    "SubjectOfBusiness-CatchLine",
    "SubjectOfBusiness-SubjectOfBusinessQualifier",
    "SubjectOfBusiness-SubjectOfBusinessTitle",
])
APPENDIX_METADATA = set([
    "Appendix-AppendixTitle",
    "Appendix-AppendixLabel",
])
EXPECTED_METADATA = {
    "AppendixContent closing": APPENDIX_METADATA,
    "Division closing": SUBJECTOFBUSINESS_METADATA | set(["Division-DivisionNumber"]),
    "Division opening": SUBJECTOFBUSINESS_METADATA,
    "Intervention closing": SUBJECTOFBUSINESS_METADATA | APPENDIX_METADATA,
    "Intervention opening": SUBJECTOFBUSINESS_METADATA | APPENDIX_METADATA,
    "MemberList closing": set(["MemberLists-MemberListsLabel", "MemberList-LabelLine", "MemberList-Note", "MemberLists-MemberListsTitle"]),
    "QuestionContent closing": SUBJECTOFBUSINESS_METADATA | set(["WrittenQuestionResponse-QuestionID"]),
    "ResponseContent closing": SUBJECTOFBUSINESS_METADATA | set(["WrittenQuestionResponse-QuestionID"]),
    "SubjectOfBusiness closing": SUBJECTOFBUSINESS_METADATA,
    "SubjectOfBusinessContent closing": SUBJECTOFBUSINESS_METADATA,
    "WrittenQuestionResponse opening": SUBJECTOFBUSINESS_METADATA,
}
STRIPPED_TAGS = {
    "Corrigendum",
    "Date",
    "ForceColumnBreak",
    "colspec",
}


# Tags where we can automatically map to HTML counterparts
TagMapping = namedtuple("TagMapping", ("wrapper", "joiner"))
HTML_MAPPING = {
    "Affiliation": TagMapping("span", ""),
    "AffiliationGroup": TagMapping("div", ""),
    "AppendixContent": TagMapping("div", ""),
    "B": TagMapping("strong", ""),
    "Committee": TagMapping("div", ""),
    "CommitteeGroup": TagMapping("div", ""),
    "CommitteeMemberGroup": TagMapping("div", ""),
    "CommitteeQuote": TagMapping("blockquote", ""),
    "Constituency": TagMapping("span", ""),
    "Content": TagMapping("div", ""),
    "DivisionType": TagMapping("div", ""),
    "Document": TagMapping("span", ""),
    "I": TagMapping("em", ""),
    "LegislationQuote": TagMapping("blockquote", ""),
    "Line": TagMapping("span", "<br />"),
    "Name": TagMapping("span", ""),
    "Motion": TagMapping("div", ""),
    "MotionBody": TagMapping("div", ""),
    "ParaText": TagMapping("p", ""),
    "Party": TagMapping("span", ""),
    "ProceduralText": TagMapping("p", ""),
    "PersonSpeaking": TagMapping("h3", ""),
    "Responder": TagMapping("span", ""),
    "Questioner": TagMapping("span", ""),
    "Poetry": TagMapping("div", ""),
    "Prayer": TagMapping("p", ""),
    "Province": TagMapping("span", ""),
    "Query": TagMapping("span", ""),
    "QuestionContent": TagMapping("div", ""),
    "Quote": TagMapping("blockquote", ""),
    "QuotePara": TagMapping("p", ""),
    "Representing": TagMapping("p", ""),
    "ResponseContent": TagMapping("div", ""),
    "Role": TagMapping("span", ""),
    "Sub": TagMapping("sub", ""),
    "Subtitle": TagMapping("span", "<br />"),
    "Sup": TagMapping("sup", ""),
    "ThroneSpeech": TagMapping("div", ""),
    "ThroneSpeechPara": TagMapping("div", ""),
    "Verse": TagMapping("p", ""),
    "entry": TagMapping("td", ""),
    "row": TagMapping("tr", ""),
    "table": TagMapping("table", ""),
    "thead": TagMapping("thead", ""),
    "tbody": TagMapping("tbody", ""),
    "title": TagMapping("span", ""),
    "tgroup": TagMapping(None, ""),
}
assert not METADATA_TAGS & set(HTML_MAPPING), METADATA_TAGS & set(HTML_MAPPING)
assert not METADATA_TAGS & set(BOUNDARY_CATEGORIES), METADATA_TAGS & set(BOUNDARY_CATEGORIES)


# Mapping person speaking names to parliamentarians
CACHED_PARLIAMENTARIANS = get_cached_dict(Parliamentarian.objects.filter(Q(birthtext__gte="1900") | Q(birthtext="")))
HONORIFICS = r"(?P<honorific>Mr|M|Ms|Mrs|Miss|Hon|Right Hon|L'hon)\.?"
SPEAKER_FORMATS = [
    re.compile(r"^{} (?P<name>[^()]*)(?P<suffix> .*)?$".format(HONORIFICS)),
    re.compile(r"^(The Acting Speaker|The Presiding Officer|The Assistant Deputy Speaker) \({} (?P<name>[^()]*)\)$".format(HONORIFICS)),
]
for alias, slug in {
    "113993": "anderson-david-2",
    "2070": "blaikie-william-alexander-bill",
    "Candice Hoeppner": "bergen-candice",
    "Chief Patrick Brazeau (National Chief of the Congress of Aboriginal Peoples)": "brazeau-patrick",
    "Daniel Hays": "hays-daniel",
    "David Chatters": "chatters-david-cameron",
    "Francis Valeriote": "valeriote-frank",
    "George Furey": "furey-george-j",
    "Harold Glenn Albrecht": "albrecht-harold",
    "Hon. David Anderson (Minister of the Environment, Lib.)": "anderson-david-1",
    "Hon. David Anderson (Victoria, Lib.)": "anderson-david-1",
    "Jean-Guy Carignan": "carignan-jean-guy",
    "Jeffrey Watson": "watson-jeff",
    "John Cummins": "cummins-john-martin",
    "Joseph Volpe": "volpe-giuseppe-joseph",
    "Judy A. Sgro": "sgro-judy",
    "Khristinn Kellie Leitch": "leitch-k-kellie",
    "Mervin Tweed": "tweed-mervin-c",
    "Michael Savage": "savage-michael-john",
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
    "Mr. Rota": "rota-anthony",
    "Mr. William Blair (Parliamentary Secretary to the Minister of Justice and Attorney General of Canada, Lib.)": "blair-bill",
    "Ms. Catterall": "catterall-marlene",
    "Norman Doyle": "doyle-norman-e",
    "Noël A. Kinsella": "kinsella-noel-a",
    "Noël Kinsella": "kinsella-noel-a",
    "Rey Pagtakhan": "pagtakhan-rey-d",
    "Richard Harris": "harris-richard-m",
    "Robert Clarke": "clarke-rob",
    "Robert Nault": "nault-robert-daniel",
    "Roy Bailey": "bailey-roy-h",
    "The Acting Speaker (Mr. Bélair)": "belair-reginald",
    "The Acting Speaker (Mr. Proulx)": "proulx-marcel",
    "The Acting Speaker (Ms. Bakopanos)": "bakopanos-eleni",
    "The Assistant Deputy Chair (Mr. Anthony Rota)": "rota-anthony",
}.items():
    CACHED_PARLIAMENTARIANS[alias].add(Parliamentarian.objects.get(slug=slug))
UNMAPPED_NAMES = {
    "Chief Phil Fontaine (National Chief of the Assembly of First Nations)",
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
    "Mr. Barack Obama (President of the United States of America)",
    "Mr. Barclay D. Howden (Director General, Directorate of Nuclear Cycle and Facilities Regulation)",
    "Mr. Barclay D. Howden",
    "Mr. Brian McGee (Senior Vice President and Chief Nuclear Officer)",
    "Mr. Brian McGee",
    "Mr. Clem Chartier (President of the Métis National Council)",
    "Mr. Daniel Meneley (Former Chief Engineer of AECL)",
    "Mr. Daniel Meneley",
    "Mr. David F. Torgerson (Executive Vice President and Chief Technology Officer and President for the Research and Technology Division AECL)",
    "Mr. David F. Torgerson",
    "Mr. Robert Strickert (Former manager of Pickering and Site VP of Darlington)",
    "Ms. Beverley Jacobs (President of the Native Women’s Association of Canada)",
    "Ms. Linda J. Keen (President and Chief Executive Officer, Canadian Nuclear Safety Commission)",
    "Ms. Linda J. Keen",
    "Ms. Linda Keen",
    "Ms. Malala Yousafzai (Co-Founder of Malala Fund)",
    "Ms. Mary Simon (President Inuit Tapiriit Kanatami)",
    "Ms. Mary Simon",
    "Right Hon. David Cameron (Prime Minister of the United Kingdom of Great Britain and Northern Ireland)",
    "The Acting Clerk of the House",
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


# Other constants
PARSED = "element-already-parsed"


class Command(BaseCommand):

    hansard_block = None
    previous_hansard_block = None

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
            except:
                logger.exception(sitting, sitting.links[EN][sources.NAME_HOC_HANSARD_XML[EN]])
                raise

    @transaction.atomic
    def fetch_hansard(self, sitting):

        # Fetch and parse the hansard XML
        self.tree = {
            lang: etree.ElementTree(etree.fromstring(fetch_url(
                sitting.links[lang][sources.NAME_HOC_HANSARD_XML[lang]],
            )))
            for lang in (EN, FR)
        }

        # Strip out incorrect elements
        for lang in (EN, FR):
            strip_empty_elements(self.tree[lang].getroot())
            for duplicate in self.tree[lang].xpath("//PersonSpeaking/Affiliation[2]"):
                duplicate.getparent().remove(duplicate)
            merge_adjacent_quotes(self.tree[lang].getroot())

        # If the structure checks out, parse down from the root
        self.floor_language = None
        self.hansard_block = None
        self.hansard_block_number = 0
        self.metadata = {}
        self.parliamentarian = None
        self.person_speaking = None
        self.previous_hansard_block = None
        self.sitting = sitting
        self.timestamp = datetimeparse(self.tree[EN].find("//ExtractedItem[@Name='MetaCreationTime']").text)
        self.new_hansard_block()
        self.parse_element(self.tree[EN].getroot())

    def parse_element(self, element, lang=None, force_unwrapped=False):

        #
        assert element is not None
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

        #
        is_boundary_tag = element.tag in BOUNDARY_CATEGORIES
        if is_boundary_tag and BOUNDARY_CATEGORIES.get(element.tag, NotBoundary).open_outer or BOUNDARY_CATEGORIES.get(element.tag, NotBoundary).open_inner:
            self.set_hansard_block_category(BOUNDARY_CATEGORIES[element.tag].open_outer)
            self.save_hansard_block(f"{element.tag} opening")
            self.set_hansard_block_category(BOUNDARY_CATEGORIES[element.tag].open_inner)

        # Custom element openings
        parse_open = getattr(self, f"{element.tag.lower()}_open", None)
        if parse_open:
            shortcut_response = parse_open(element, lang)
            if shortcut_response is not None:
                return shortcut_response

        # Recurse down into the children
        if lang is None and element.tag in CONTENT_MAY_DIFFER:
            child_responses = self.parse_children(element, EN, is_boundary_tag)
            try:
                french_element = self.get_french_element(element)
                french_element.attrib[PARSED] = "True"
                child_responses.update(self.parse_children(french_element, FR, is_boundary_tag))
            except:
                # Error handling to account for the same problem as self.parse_text_node
                pass
        else:
            child_responses = self.parse_children(element, lang, is_boundary_tag)

        if is_boundary_tag:
            self.set_hansard_block_category(BOUNDARY_CATEGORIES[element.tag].close_inner)

        # Custom element closings
        parse_close_func = getattr(self, f"{element.tag.lower()}_close", None)
        if parse_close_func:
            parse_close_func(element, lang, child_responses)
            child_responses = {}

        # Parse the element closing
        if element.tag in METADATA_TAGS:
            self.metadata[(element.getparent().tag, element.tag)] = {
                lang: "".join(content)
                for lang, content in child_responses.items()
            }
            response = {}
        elif is_boundary_tag and BOUNDARY_CATEGORIES.get(element.tag, NotBoundary).close_inner or BOUNDARY_CATEGORIES.get(element.tag, NotBoundary).close_outer:
            assert not any(content for lang, content in child_responses.items()), "Unparsed content for boundary tag?"
            self.set_hansard_block_category(BOUNDARY_CATEGORIES[element.tag].close_inner)
            self.save_hansard_block(f"{element.tag} closing")
            self.set_hansard_block_category(BOUNDARY_CATEGORIES[element.tag].close_outer)
            response = {}
        elif element.tag in HTML_MAPPING:
            response = {
                lang: "".join((
                    """<{html_tag} class="{xml_tag}"{data}>""".format(
                        html_tag=HTML_MAPPING[element.tag].wrapper,
                        xml_tag=element.tag.lower(),
                        data="".join(filter(None, (
                            f' data-language="{self.floor_language}"' if HTML_MAPPING[element.tag].wrapper in ("p", "blockquote") else None,
                            f' data-toctype="{element.attrib["ToCType"]}"' if "ToCType" in element.attrib else None,
                            f' data-type="{element.attrib["Type"]}"' if "Type" in element.attrib else None,
                        )))
                    ) if HTML_MAPPING[element.tag].wrapper and not force_unwrapped else "",
                    HTML_MAPPING[element.tag].joiner.join(content).strip(),
                    """</{html_tag}>""".format(
                        html_tag=HTML_MAPPING[element.tag].wrapper,
                    ) if HTML_MAPPING[element.tag].wrapper and not force_unwrapped else "",
                ))
                for lang, content in child_responses.items()
            }
        else:
            raise Exception(f"UNEXPECTED TAG (not metadata/boundary/html): {element.tag}")

        if element.tag not in METADATA_TAGS and element.tag not in TAGS_THAT_KEEP_METADATA_ON_CLOSING:
            self.clear_metadata(element.tag)

        return response

    def get_french_element(self, el_en, by_attrib=None):
        if by_attrib:
            return one_or_none(self.tree[FR].xpath(f"//{el_en.tag}[@{by_attrib} = '{el_en.attrib[by_attrib]}']"))
        else:
            return one_or_none(self.tree[FR].xpath(self.tree[EN].getpath(el_en)))

    def parse_children(self, element, selected_lang, element_has_hansard_block=False):
        response = defaultdict(list)
        for child in element.xpath("child::node()"):
            parsed = self.parse_element(child, selected_lang)
            for lang, content in parsed.items():
                if element_has_hansard_block:
                    self.hansard_block.content[lang].append(content)
                else:
                    response[lang].append(content)
        return dict(response)

    def new_hansard_block(self):
        if self.hansard_block is not None:
            self.save_hansard_block()
        self.hansard_block_number += 1
        self.hansard_block = models.HansardBlock(
            sitting=self.sitting,
            number=self.hansard_block_number,
            slug="{}-{}".format(self.sitting.slug, self.hansard_block_number),
            start_approx=self.timestamp,
            previous=self.previous_hansard_block,
            category=None,
            content={EN: [], FR: []},
            metadata={EN: {}, FR: {}},
        )

    def set_hansard_block_category(self, category):
        if category and category != self.hansard_block.category:
            assert not self.hansard_block.category, f"Category already set to {self.hansard_block.get_category_display()} and then tried to set to {category}"
            self.hansard_block.category = category

    def save_hansard_block(self, reason="No reason supplied"):
        if any(content for lang, content in self.hansard_block.content.items()):
            self.hansard_block.parliamentarian = self.parliamentarian
            self.hansard_block.content = {
                lang: "\n".join(content)
                for lang, content in self.hansard_block.content.items()
            }
            self.hansard_block.metadata = {
                "-".join(k): v
                for k, v in self.metadata.items()
            }
            unexpected_metadata = set(self.hansard_block.metadata.keys()) - EXPECTED_METADATA.get(reason, set())
            assert not unexpected_metadata, f"{reason}, {unexpected_metadata}, {self.hansard_block.content[EN]}"
            self.hansard_block.metadata["Intervention-PersonSpeaking"] = self.person_speaking
            if self.hansard_block.category == models.HansardBlock.CATEGORY_UNEXPECTED:
                logger.warning("UNEXPECTED", reason, self.hansard_block.content)
            self.hansard_block.save()
            self.previous_hansard_block = self.hansard_block
            self.hansard_block = None

            self.new_hansard_block()
        else:
            self.hansard_block.category = None
        self.person_speaking = None
        self.parliamentarian = None

    def assert_no_stray_content(self):
        for lang, content in self.hansard_block.content.items():
            assert not content, "Stray content? {}".format(content)

    def clear_metadata(self, *tags):
        self.metadata = {
            k: v
            for k, v in self.metadata.items()
            if k[0] not in tags
        }

    def parse_text_node(self, element, lang):
        if not element.strip():
            response = {}
        elif lang:
            response = {lang: str(element)}
        else:
            try:
                response = {
                    EN: str(element),
                    FR: str(self.get_french_element(element.getparent()).text),
                }
            except AttributeError:
                # In some odd cases, the two hansards don't match up. Consider the example
                # of http://www.noscommunes.ca/Content/House/402/Debates/085/HAN085-E.XML
                # and its French counterpart. <SubjectOfBusiness id="2870025"> is qualified
                # in English as "Health", but unqualified in French. I've contacted
                # infohoc@parl.gc.ca to see about having this fixed.
                response = {
                    EN: str(element),
                }
        return normalize_whitespace(response, strip=False)

    # Opening handlers
    # ------------------------------------------------------------------------

    def orderofbusiness_open(self, element, lang):
        self.metadata[(element.tag, "Rubric")] = element.attrib["Rubric"]

    def paratext_open(self, element, lang):
        quotes = element.xpath("Quote")
        if quotes:
            assert len(quotes) == 1
            assert quotes[0].tail is None
            return self.parse_element(quotes[0], lang)

    def startpagenumber_open(self, element, lang):
        return {}

    def documenttitle_open(self, element, lang):
        return {}

    def extractedinformation_open(self, element, lang):
        return {}

    def timestamp_open(self, element, lang):
        # We use a timedelta here instead as some timestamps push us into hour 24
        # (e.g. http://www.noscommunes.ca/Content/House/412/Debates/097/HAN097-E.XML)
        self.timestamp = make_aware(datetime(self.sitting.date.year, self.sitting.date.month, self.sitting.date.day)) + timedelta(
            hours=int(element.attrib["Hr"]),
            minutes=int(element.attrib["Mn"]),
        )
        return {}

    def floorlanguage_open(self, element, lang):
        self.floor_language = element.attrib["language"]
        return {}

    def personspeaking_open(self, element, lang):
        assert not self.person_speaking and not self.parliamentarian, "Person speaking opened, but wasn't flushed"
        affiliation = element.find("Affiliation")
        if affiliation is None:
            return
        try:
            self.person_speaking = normalize_whitespace({
                EN: affiliation.text,
                FR: self.get_french_element(element).xpath("Affiliation")[0].text,
            }, strip=True)
        except:
            pass
        if not self.person_speaking or not self.person_speaking[EN]:
            self.person_speaking = normalize_whitespace({
                EN: element.getparent().attrib["ToCText"],
                FR: self.get_french_element(element.getparent(), by_attrib="id").attrib["ToCText"],
            }, strip=True)

        if self.person_speaking[EN] not in UNMAPPED_NAMES:
            try:
                self.parliamentarian = get_cached_obj(
                    CACHED_PARLIAMENTARIANS,
                    affiliation.attrib["DbId"]
                )
            except:
                try:
                    self.parliamentarian = get_cached_obj(CACHED_PARLIAMENTARIANS, self.person_speaking[EN])
                except AssertionError:
                    for speaker_format in SPEAKER_FORMATS:
                        match = speaker_format.search(self.person_speaking[EN])
                        if match:
                            try:
                                self.parliamentarian = get_cached_obj(
                                    CACHED_PARLIAMENTARIANS,
                                    normalize_whitespace(match.groupdict()["name"], strip=True),
                                )
                            except AssertionError:
                                logger.warning("UNMATCHED SPEAKER", self.sitting, affiliation.attrib, [self.person_speaking[EN], match.groupdict()["name"].strip()], element.getparent().attrib)
                            break
                    else:
                        logger.warning("SPEAKER FORMAT MISMATCH", self.sitting, [self.person_speaking[EN]], element.getparent().attrib)
                if self.parliamentarian:
                    CACHED_PARLIAMENTARIANS[affiliation.attrib["DbId"]].add(self.parliamentarian)
        return {}

    def questioner_open(self, *args):
        return self.personspeaking_open(*args)

    def responder_open(self, *args):
        return self.personspeaking_open(*args)

    def intervention_open(self, element, lang):
        self.intervention_type = element.attrib.get("Type", None)

    # Closing handlers
    # ------------------------------------------------------------------------

    def writtenquestionresponse_close(self, *args):
        self.clear_metadata("WrittenQuestion", "WrittenResponse")

    def questioncontent_close(self, element, lang, child_responses):
        for lang, content in child_responses.items():
            self.hansard_block.content[lang].append("".join(content))

    def responsecontent_close(self, element, lang, child_responses):
        for lang, content in child_responses.items():
            self.hansard_block.content[lang].append("".join(content))

    def affiliationgroup_close(self, element, lang, child_responses):
        for lang, content in child_responses.items():
            self.hansard_block.content[lang].append("".join((
                """<span class="title">{}</span>""".format(self.metadata.get(("AffiliationGroup", "Title"), {}).get(lang, "")),
                """<span class="total">{}</span""".format(self.metadata.get(("AffiliationGroup", "Total"), {}).get(lang, "")),
                """<ul>{}</ul>""".format("".join(f"<li>{c}</li>" for c in content)),
            )))
        self.clear_metadata("AffiliationGroup")

    def divisiontype_close(self, element, lang, child_responses):
        for lang, content in child_responses.items():
            self.hansard_block.content[lang].append("".join((
                """<span class="title">{}</span>""".format(self.metadata.get(("DivisionType", "Title"), {}).get(lang, "")),
                """<span class="type">{}</span>""".format(self.metadata.get(("DivisionType", "Type"), {}).get(lang, "")),
                """<ul>{}</ul>""".format("".join(f"<li>{c}</li>" for c in content)),
                """<span class="total">{}</span""".format(self.metadata.get(("DivisionType", "Total"), {}).get(lang, "")),
            )))
        self.clear_metadata("DivisionType")


def normalize_whitespace(content, strip):
    if isinstance(content, str):
        response = WHITESPACE.sub(" ", content)
        return response.strip() if strip else response
    else:
        return {
            lang: normalize_whitespace(string, strip)
            for lang, string in content.items()
        }


def merge_adjacent_quotes(element):
    if isinstance(element, _ElementUnicodeResult):
        return

    children = list(element)
    for left, right in zip(children[:-1], children[1:]):
        if all((
            left.tag == right.tag,
            set(map(lambda child: child.tag, list(left))) in (set(["Quote"]), set(["QuotePara"])),
            set(map(lambda child: child.tag, list(right))) in (set(["Quote"]), set(["QuotePara"])),
            not left.text,
            not right.text,
        )):
            for child in reversed(left):
                right.insert(0, child)
            left.getparent().remove(left)

    for child in element:
        merge_adjacent_quotes(child)


def strip_empty_elements(element):
    if isinstance(element, _ElementUnicodeResult):
        return

    for child in element.xpath("child::node()"):
        strip_empty_elements(child)

    if isinstance(element, _ProcessingInstruction):
        element.getparent().remove(element)
    elif element.tag in STRIPPED_TAGS:
        element.getparent().remove(element)
    elif not len(element):
        if (element.text is None or not element.text.strip()) and element.tag != "Affiliation":
            element.getparent().remove(element)

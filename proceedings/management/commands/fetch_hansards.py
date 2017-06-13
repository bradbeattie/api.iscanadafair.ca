from collections import namedtuple, defaultdict
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


# Sittings with identified issues
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
TAGS_THAT_OPEN_WITH_HANSARD_BLOCKS = {
    "Appendix": models.HansardBlock.CATEGORY_APPENDIX,
    "Division": models.HansardBlock.CATEGORY_DIVISION,
    "Intervention": models.HansardBlock.CATEGORY_INTERVENTION,
    "Intro": models.HansardBlock.CATEGORY_INTRO,
    "MemberList": models.HansardBlock.CATEGORY_MEMBERLIST,
    "Questioner": models.HansardBlock.CATEGORY_WRITTEN_QUESTION,
    "Responder": models.HansardBlock.CATEGORY_WRITTEN_QUESTION,

    "SubjectOfBusinessContent": models.HansardBlock.CATEGORY_UNKNOWN,
    "WrittenQuestionResponse": models.HansardBlock.CATEGORY_UNKNOWN,
}
TAGS_THAT_CLOSE_WITH_HANSARD_BLOCKS = {
    "Appendix",
    "Division",
    "Intervention",
    "Hansard",
    "HansardBody",
    "Intro",
    "MemberList",
    "MemberLists",
    "OrderOfBusiness",
    "SubjectOfBusiness",
    "SubjectOfBusinessContent",
    "QuestionContent",
    "ResponseContent",
    "WrittenQuestionResponse",
}
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
    "ProceduralText",
    "Title",
    "Total",
    "Type",
}
STRIPPED_TAGS = {
    "ForceColumnBreak",
    "Corrigendum",
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


# Mapping person speaking names to parliamentarians
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


# Expected XML structure
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
    "row": "({entry})+",
    "table": "({title})?{tgroup}",
    "tbody": "({row})+",
    "tgroup": "{tbody}",
}
COMPILED_STRUCTURE = {
    k: re.compile(f"^{v}$")
    for k, v in PATTERN_STRUCTURE.items()
}
LEAF = re.compile("^$")


# Other constants
PARSED = "element-already-parsed"
SAID_PREFIX = re.compile(r"^(He|She) said: ")  # TODO: USE THIS


class Command(BaseCommand):

    hansard_block = None
    previous_hansard_block = None

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        for sitting in tqdm(
            models.Sitting.objects.filter(links__contains=sources.NAME_HOC_HANSARD_XML[EN], slug="40-3-113"),
            desc="Fetch Hansards, HoC",
            unit="sitting",
        ):
            try:
                self.fetch_hansard(sitting)
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
        is_boundary_tag = element.tag in TAGS_THAT_OPEN_WITH_HANSARD_BLOCKS
        if is_boundary_tag:
            self.save_hansard_block(f"boundary tag opening: {element.tag}")
            self.hansard_block.category = TAGS_THAT_OPEN_WITH_HANSARD_BLOCKS[element.tag]

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
            return {}
        elif element.tag in TAGS_THAT_CLOSE_WITH_HANSARD_BLOCKS:
            assert not any(content for lang, content in child_responses.items()), "Unparsed content for boundary tag?"
            self.save_hansard_block(f"boundary tag closing: {element.tag}")
            return {}
        elif element.tag in HTML_MAPPING:
            response = {
                lang: "".join((
                    """<{html_tag} class="{xml_tag}"{data_lang}>""".format(
                        html_tag=HTML_MAPPING[element.tag].wrapper,
                        xml_tag=element.tag.lower(),
                        data_lang=f' data-language="{self.floor_language}"' if HTML_MAPPING[element.tag].wrapper in ("p", "blockquote") else "",
                    ) if HTML_MAPPING[element.tag].wrapper and not force_unwrapped else "",
                    HTML_MAPPING[element.tag].joiner.join(content).strip(),
                    """</{html_tag}>""".format(
                        html_tag=HTML_MAPPING[element.tag].wrapper,
                    ) if HTML_MAPPING[element.tag].wrapper and not force_unwrapped else "",
                ))
                for lang, content in child_responses.items()
            }
            return response
        else:
            raise Exception(f"UNEXPECTED TAG (not boundary or html): {element.tag}")

    def get_french_element(self, el_en):
        return one_or_none(self.tree[FR].xpath(self.tree[EN].getpath(el_en)))

    def parse_children(self, element, selected_lang, is_boundary_tag=False):
        response = defaultdict(list)
        for child in element.xpath("child::node()"):
            parsed = self.parse_element(child, selected_lang)
            for lang, content in parsed.items():
                if is_boundary_tag:
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
            category=models.HansardBlock.CATEGORY_UNKNOWN,
            content={EN: [], FR: []},
            metadata={EN: {}, FR: {}},
        )

    def save_hansard_block(self, reason="No reason supplied"):
        if any(content for lang, content in self.hansard_block.content.items()):
            self.hansard_block.parliamentarian = self.parliamentarian
            self.hansard_block.content = {
                lang: "\n".join(content)
                for lang, content in self.hansard_block.content.items()
            }
            self.hansard_block.metadata = {
                "".join(k): v
                for k, v in self.metadata.items()
            }
            self.hansard_block.metadata["reason"] = reason
            self.hansard_block.save()

            self.previous_hansard_block = self.hansard_block
            self.hansard_block = None
            self.person_speaking = None
            self.parliamentarian = None
            self.new_hansard_block()

    def assert_no_stray_content(self):
        for lang, content in self.hansard_block.content.items():
            assert not content, "Stray content? {}".format(content)

    def clear_metadata(self, element):
        self.metadata = {
            k: v
            for k, v in self.metadata.items()
            if k[0] != element.tag
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
        affiliation = element.xpath("Affiliation")
        print("AFFILIATION?", lang, element.attrib, element.getparent().attrib, element.getparent().getparent().attrib)
        try:
            self.person_speaking = normalize_whitespace({
                EN: affiliation[0].text or element.getparent().attrib["ToCText"],
                FR: self.get_french_element(element).xpath("Affiliation")[0].text or self.get_french_element(element.getparent()).attrib["ToCText"],
            }, strip=True)
        except IndexError:
            return
        if self.person_speaking[EN] not in UNMAPPED_NAMES:
            try:
                self.parliamentarian = get_cached_obj(
                    CACHED_PARLIAMENTARIANS,
                    affiliation.attrib["DbId"]
                )
            except:
                try:
                    self.parliamentarian = get_cached_obj(
                        CACHED_PARLIAMENTARIANS,
                        MAPPED_PARLIAMENTARIANS_BY_TITLE[self.person_speaking[EN]]
                    )
                except KeyError:
                    for speaker_format in SPEAKER_FORMATS:
                        match = speaker_format.search(self.person_speaking[EN])
                        if match:
                            try:
                                name = normalize_whitespace(match.groupdict()["name"], strip=True)
                                self.parliamentarian = get_cached_obj(
                                    CACHED_PARLIAMENTARIANS,
                                    MAPPED_PARLIAMENTARIANS_BY_NAME.get(name, name),
                                )
                            except AssertionError:
                                print("UNMATCHED SPEAKER", self.sitting, [self.person_speaking[EN], match.groupdict()["name"].strip()])
                            break
                    else:
                        print("SPEAKER FORMAT MISMATCH", self.sitting, [self.person_speaking[EN]])
                if self.parliamentarian:
                    try:
                        CACHED_PARLIAMENTARIANS[affiliation.attrib["DbId"]].add(
                            self.parliamentarian
                        )
                    except:
                        pass

    def questioner_open(self, *args):
        return self.personspeaking_open(*args)

    def responder_open(self, *args):
        return self.personspeaking_open(*args)

    def intervention_open(self, element, lang):
        self.intervention_type = element.attrib.get("Type", None)

    # Closing handlers
    # ------------------------------------------------------------------------

    def intervention_close(self, element, lang, child_responses):
        self.intervention_type = None
        self.person_speaking = None

    def questioncontent_close(self, element, lang, child_responses):
        for lang, content in child_responses.items():
            self.hansard_block.content[lang].append("".join(content))

    def responsecontent_close(self, element, lang, child_responses):
        for lang, content in child_responses.items():
            self.hansard_block.content[lang].append("".join(content))

    def divisiontype_close(self, element, lang, child_responses):
        for lang, content in child_responses.items():
            self.hansard_block.content[lang].append("".join((
                "<span class='title'>{}</span".format(self.metadata.pop(('DivisionType', 'Title'), {}).get(lang, "")),
                "<span class='type'>{}</span".format(self.metadata.pop(('DivisionType', 'Type'), {}).get(lang, "")),
                "<ul>{}</ul>".format("".join(f"<li>{c}</li>" for c in content)),
                "<span class='total'>{}</span".format(self.metadata.pop(('DivisionType', 'Total'), {}).get(lang, "")),
            )))


def normalize_whitespace(content, strip):
    if isinstance(content, str):
        response = WHITESPACE.sub(" ", content)
        return response.strip() if strip else response
    else:
        return {
            lang: normalize_whitespace(string, strip)
            for lang, string in content.items()
        }


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
        pass
        #if (element.text is None or not element.text.strip()) and element.tag != "Affiliation":
        #    element.getparent().remove(element)


Structure = namedtuple("Structure", ("tag", "id", "children"))
def get_child_structure(element, include_text_nodes=False, depth=1):
    if isinstance(element, _ElementUnicodeResult):
        return Structure("TEXT", None, []) if element.strip() else None
    elif not depth:
        return Structure(element.tag, element.attrib.get("id", None), [])
    elif include_text_nodes:
        return Structure(
            element.tag,
            element.attrib.get("id", None),
            list(filter(None, [
                get_child_structure(child, include_text_nodes=include_text_nodes, depth=depth - 1)
                for child in element.xpath("child::node()")
            ])),
        )
    else:
        return Structure(
            element.tag,
            element.attrib.get("id", None),
            [
                get_child_structure(child, include_text_nodes=include_text_nodes, depth=depth - 1)
                for child in element
            ],
        )


def assert_child_structure(element):
    child_structure = "".join(map(lambda x: f"{{{x}}}", get_child_structure(element)))
    expected = COMPILED_STRUCTURE.get(element.tag, LEAF)
    assert expected.search(child_structure), f"{element.tag} expected {expected} but got {child_structure}"

from collections import namedtuple, defaultdict
from datetime import datetime, time, timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from federal_common import sources
from federal_common.sources import EN, FR
from federal_common.utils import fetch_url, one_or_none
from lxml import etree
from lxml.etree import _ProcessingInstruction, _ElementUnicodeResult
from pprint import pprint
from proceedings import models
from tqdm import tqdm
import logging
import pytz
import random
import re


logger = logging.getLogger(__name__)
TZ = pytz.timezone(settings.TIME_ZONE)
INCONSISTENT_IDS = (
    "ParaText",
    "Intervention",
)
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
CONTEXT_FLAGS = ("FloorLanguage", "Timestamp", "ProceduralText")
DEV_GROUP = ("FloorLanguage", "Timestamp", "PersonSpeaking")
PARSED = "element-already-parsed"
HTML_MAPPING = {
    "ParaText": "p",
    "I": "em",
    "B": "strong",
    "Sup": "sup",
    "Sub": "sub",
    "Quote": "blockquote",
    "QuotePara": "p",
}
Rendering = namedtuple("Rendering", ("tag", "content"))


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
    timestamp_start = None
    timestamp_finish = None
    subject_of_business = None
    order_of_business = None
    person_speaking = None
    hansard_block_index = None
    sitting = None

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        for sitting in tqdm(
            [
                sitting
                for sitting in random.sample(list(models.Sitting.objects.all()), 10)
                if sources.NAME_HOC_HANSARD_XML[EN] in sitting.links[EN]
            ],
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
        pprint(get_child_structure(self.tree[EN].getroot(), include_text_nodes=True, depth=1000), width=150)
        self.hansard_block_index = 0
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

    def get_hansard_block_index(self):
        self.hansard_block_index += 1
        return self.hansard_block_index

    def parse(self, element, lang=None):
        # print("PARSE", element, element.getparent())

        #
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
                child_responses.update(self.get_child_responses(self.get_french_element(element), FR))
            except:
                # Error handling to account for the same problem as self.parse_text_node
                pass
        else:
            child_responses = self.get_child_responses(element, lang)

        # Parse the element closing
        parse_close = getattr(self, f"{element.tag.lower()}_close", None)
        if parse_close:
            return parse_close(element, child_responses, lang)
        elif any((
            element.tag not in PATTERN_STRUCTURE,
            PATTERN_STRUCTURE.get(element.tag, None) == TITLE_TEXT,
            element.tag in ("Affiliation", "PersonSpeaking"),
        )):
            return {
                lang: "".join(content)
                for lang, content in child_responses.items()
            }
        elif element.tag in HTML_MAPPING:
            return {
                lang: "<{tag}>{joined_content}</{tag}>".format(
                    tag=HTML_MAPPING[element.tag],
                    joined_content="".join(content).strip(),
                )
                for lang, content in child_responses.items()
            }
        else:
            return self.unparsed(element, child_responses, lang)

    def extractedinformation(self, element, lang):
        # TODO: Do we want to do anything with this subtree? Maybe create a HansardBlock to open the session?
        return {}

    def timestamp_open(self, element, lang):
        self.timestamp = (int(element.attrib["Hr"]), int(element.attrib["Mn"]))
        return {}

    def floorlanguage_open(self, element, lang):
        self.floor_language = element.attrib["language"]
        return {}

    def personspeaking_open(self, element, lang):
        return self.parse(element.find("Affiliation"), lang)

    def questioner_open(self, *args):
        return self.personspeaking_open(*args)

    def responder_open(self, *args):
        return self.personspeaking_open(*args)

    def subjectofbusiness_open(self, element, lang):
        self.subject_of_business = list(map(lambda x: (x, self.parse(x, lang)), filter(lambda x: x is not None, (
            element.find(tag)
            for tag in ("SubjectOfBusinessTitle", "SubjectOfBusinessQualifier", "CatchLine")
        ))))

    def subjectofbusiness_close(self, element, child_responses, lang):
        self.subject_of_business = None
        return {}

    def subjectofbusinesscontent_open(self, element, lang):
        child_responses = self.get_child_responses(element, lang)
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

    def orderofbusiness_close(self, element, child_responses, lang):
        self.order_of_business = None
        return {}

    def intervention_open(self, element, lang):
        self.timestamp_start = self.timestamp
        self.person_speaking = self.parse(element.find("PersonSpeaking"), lang)

    def intervention_close(self, element, child_responses, lang):
        self.timestamp_finish = self.timestamp
        # TODO: Augment the intervention with SoB and OoB
        hansard_block = models.HansardBlock(
            sitting=self.sitting,
            index=self.get_hansard_block_index(),
            start_approx=datetime.combine(self.sitting.date, time(0), TZ) + timedelta(  # We use a timedelta here instead as some timestamps push us into hour 24 (e.g. http://www.noscommunes.ca/Content/House/412/Debates/097/HAN097-E.XML)
                hours=self.timestamp_start[0],
                minutes=self.timestamp_start[1],
            ),
            content={
                lang: "\n".join(content)
                for lang, content in child_responses.items()
            },
            parliamentarian=None,  # TODO: Use self.person_speaking to populate this
        )
        hansard_block.slug = "{}-{}".format(hansard_block.sitting.slug, hansard_block.index)
        hansard_block.save()
        return {}

    def content_close(self, element, child_responses, lang):
        return {
            lang: "\n".join(content)
            for lang, content in child_responses.items()
        }

    def questioncontent_close(self, *args):
        return self.content_close(*args)

    def responsecontent_close(self, *args):
        return self.content_close(*args)

    def parse_text_node(self, element, lang):
        if not element.strip():
            return {}
        elif lang:
            return {
                lang: str(element),
            }
        else:
            try:
                return {
                    EN: str(element),
                    FR: str(self.get_french_element(element.getparent()).text),
                }
            except AttributeError:
                # In some odd cases, the two hansards don't match up. Consider the example
                # of http://www.noscommunes.ca/Content/House/402/Debates/085/HAN085-E.XML
                # and its French counterpart. <SubjectOfBusiness id="2870025"> is qualified
                # in English as "Health", but unqualified in French. I've contacted
                # infohoc@parl.gc.ca to see about having this fixed.
                return {
                    EN: str(element),
                }

    def unparsed(self, element, child_responses, lang):
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

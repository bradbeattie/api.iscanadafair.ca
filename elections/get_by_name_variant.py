from collections import defaultdict
from django.db import transaction
from django.utils.text import slugify
from elections import models
from jellyfish import jaro_distance
from unidecode import unidecode
import re


class SkippedObject(Exception):
    pass


SPACERS = re.compile(r"({})".format("|".join((
    "\xa0",
))), re.I)
DASHERS = re.compile(r"({})".format("|".join((
    "–",
    "—",
))), re.I)
PARTY_BLANKER = re.compile(r"({})".format("|".join((
    "^party-for-",
    "-party-of-canada$",
    "-party$",
))), re.I)
RIDING_BLANKER = re.compile(r" \(.*electoral district\)$")
TITLE_REGEX = re.compile(r"^(Mr\.|Ms\.|Mrs\.|The Honourable|The Right Honourable|Senator) ")



def massage(string):
    string = DASHERS.sub("--", string)
    string = SPACERS.sub(" ", string)
    string = slugify(unidecode(string.split("/")[0].strip())).lower()
    string = PARTY_BLANKER.sub("", string)  # TODO: This shouldn't be in the generic massage function
    return string


def names_by_distance(search_names, model, *args, **kwargs):
    massaged_search_names = [massage(search_name) for search_name in search_names]
    for pk, name, name_variants in model.objects.filter(*args, **kwargs).distinct().values_list("pk", "name", "name_variants"):
        for considered_name in [name, *name_variants.values()]:
            for massaged_search_name in massaged_search_names:
                yield (jaro_distance(massaged_search_name, massage(considered_name)), pk, considered_name)
                if considered_name == massaged_search_name:
                    raise StopIteration


def ask_for_instance(search_names, model, search_name_source, *args, **kwargs):
    while True:
        options_matched = defaultdict(list)
        options_partial = defaultdict(list)

        # Hunt for matches
        for index, (distance, pk, name) in enumerate(sorted(names_by_distance(search_names, model, *args, **kwargs), reverse=True)):
            if distance == 1:
                options_matched[pk].append(name)
            else:
                options_partial[pk].append(name)
            if index > 3 or distance < 0.5:
                break

        # If we find an exact match, return it
        if len(options_matched) == 1:
            pk, option_names = list(options_matched.items())[0]
            return model.objects.get(pk=pk)

        # If we find multiple exact matches or multiple partial matches, ask which to use
        options = options_matched or options_partial
        print("\n{}: {} {}".format(search_name_source, search_names, kwargs))
        for pk, names in options.items():
            print("\t{:>5}: {}".format(pk, names))
        selection = input("\tMatch? ")

        if selection == "skip":
            raise SkippedObject()
        try:
            if int(selection or 0) in options:
                return model.objects.get(pk=int(selection))
            else:
                print("That wasn't one of the options.")
        except ValueError:
            search_names = [selection]


@transaction.atomic
def get_object(model, *args, **kwargs):
    can_ask_for_input = kwargs.pop("can_ask_for_input", True)
    search_name_source = kwargs.pop("search_name_source", None)
    search_name_initial = kwargs.pop("name").replace("  ", " ")
    search_name_corrected = kwargs.pop("search_name_corrected", None) or search_name_initial
    if search_name_corrected == SkippedObject:
        raise SkippedObject
    if isinstance(search_name_corrected, str):
        search_name_corrected = [search_name_corrected]

    try:
        instance = model.objects.filter(name__in=search_name_corrected, *args, **kwargs).distinct().get()
    except model.DoesNotExist as e:
        if can_ask_for_input:
            instance = ask_for_instance(search_name_corrected, model, search_name_source, *args, **kwargs)
            if not search_name_source:
                raise Exception("Need search_name_source", instance)
        else:
            raise

    if search_name_initial == instance.name:
        return instance
    elif search_name_initial in instance.name_variants.values():
        return instance
    else:
        instance.name_variants[search_name_source] = search_name_initial
        instance.save()
        return instance


def get_province(*args, **kwargs):
    kwargs["search_name_corrected"] = {
        "P.E.I.": "Prince Edward Island",
        "B.C.": "British Columbia",
        "Newfoundland & Labrador": "Newfoundland and Labrador",
        "Newfoundland": "Newfoundland and Labrador",
        "Yukon Territory": "Yukon",
    }.get(kwargs["name"], None)
    return get_object(models.Province, *args, **kwargs)


def get_party(*args, **kwargs):
    kwargs["search_name_corrected"] = {
        ("Elections Canada", "Animal Protection Party of Canada"): "Animal Alliance Environment Voters Party of Canada",
        ("Elections Canada", "Canada Party"): "C.P. (2)",
        ("Elections Canada", "Conservative Party of Canada"): "C",
        ("Elections Canada", "Forces et Démocratie"): "Strength in Democracy",
        ("Elections Canada", "Rhinoceros Party"): "Rhino (2)",
        ("Library of Parliament, Parliament Details", "Conservative (1867-1942)"): "Cons.",
        ("Library of Parliament, Parliament Details", "Conservative Party of Canada"): "C",
        ("Library of Parliament, Parliament Details", "Unionist (Conservative and Liberal)"): "Unionist",
        ("Library of Parliament, Political Parties", "Canada Party"): "C.P. (2)",
        ("Library of Parliament, Political Parties", "Canadian Reform Conservative Alliance"): "Canadian Alliance",
        ("Library of Parliament, Political Parties", "Conservative Party of Canada"): "C",
        ("Library of Parliament, Political Parties", "Progressive Conservative Democratic Representative Coalition"): SkippedObject,
        ("Wikipedia", "Anti-Confederation Party"): "Anti-Confederate",
        ("Wikipedia", "Bloc populaire"): "Bloc populaire canadien",
        ("Wikipedia", "Canada Party (2015)"): "C.P. (2)",
        ("Wikipedia", "Canada Party"): "C.P. (1)",
        ("Wikipedia", "Communist Party of Canada (Marxist–Leninist)"): "Marxist-Leninist Party of Canada",
        ("Wikipedia", "Confederation of Regions Party of Canada"): "Confederation of Regions Western Party",
        ("Wikipedia", "Conservative Party of Canada (1867–1942)"): "Cons.",
        ("Wikipedia", "Conservative Party of Canada"): "C",
        ("Wikipedia", "Democratic Party of Canada"): "Democrat",
        ("Wikipedia", "Democratic Representative Caucus"): SkippedObject,
        ("Wikipedia", "Equal Rights Party (Canada)"): "Equal Rights",
        ("Wikipedia", "Marijuana Party (Canada)"): "Marijuana Party",
        ("Wikipedia", "McCarthyite candidates 1896"): "McCarthyite",
        ("Wikipedia", "Parti canadien (1942)"): SkippedObject,
        ("Wikipedia", "Progressive-Conservative (candidate)"): SkippedObject,
        ("Wikipedia", "Republican Party (Canada)"): "Republican",
        ("Wikipedia", "Rhinoceros Party of Canada (1963–1993)"): "Rhino (1)",
        ("Wikipedia", "Socialist Labour Party (Canada)"): "Socialist Labour",
        ("Wikipedia", "Socialist Party of Canada (WSM)"): "Soc (2)",
        ("Wikipedia", "Socialist Party of Canada"): "Soc (1)",
        ("Wikipedia", "Union des électeurs"): "Union of Electors",
        ("Parliament, Chamber Vote Detail", "Conservative"): "C",
        ("Parliament, Chamber Vote Detail", "Conservative Independent"): "I Con",
        ("Parliament, Chamber Vote Detail", "Independent"): SkippedObject,
    }.get((kwargs["search_name_source"], kwargs["name"]), None)
    return get_object(models.Party, *args, **kwargs)


def get_riding(*args, **kwargs):
    kwargs["name"] = RIDING_BLANKER.sub("", kwargs["name"])
    if "province" in kwargs:
        kwargs["search_name_corrected"] = {
            ("Elections Canada, General Election 36 (1997-06-02)", "Alberta", "Medecine Hat"): "MEDICINE HAT",
            ("Elections Canada, General Election 36 (1997-06-02)", "Newfoundland and Labrador", "Burin–St. Georges's"): "BURIN--ST. GEORGE'S",
            ("Elections Canada, General Election 36 (1997-06-02)", "Ontario", "Etibocoke Centre"): "ETOBICOKE CENTRE",
            ("Elections Canada, General Election 36 (1997-06-02)", "Ontario", "Ottawa West"): "OTTAWA WEST--NEPEAN",
            ("Elections Canada, General Election 36 (1997-06-02)", "Quebec", "Mount Royal"): "MONT ROYAL",
            ("Library of Parliament, Related", "Alberta", "ASSINIBOIA WEST"): SkippedObject,
            ("Library of Parliament, Related", "Alberta", "GRANDE PRAIRIE"): SkippedObject,
            ("Library of Parliament, Related", "Alberta", "RED DEER--WOLF CREEK"): SkippedObject,
            ("Library of Parliament, Related", "Alberta", "STURGEON RIVER"): SkippedObject,
            ("Library of Parliament, Related", "British Columbia", "LANGLEY--MATSQUI"): SkippedObject,
            ("Library of Parliament, Related", "British Columbia", "SAANICH--ESQUIMALT--JUAN DE FUCA"): SkippedObject,
            ("Library of Parliament, Related", "Manitoba", "WINNIPEG--ST. PAUL"): SkippedObject,
            ("Library of Parliament, Related", "Newfoundland and Labrador", "HUMBER--ST. BARBE"): SkippedObject,
            ("Library of Parliament, Related", "Northwest Territories", "ALBERTA"): "ALBERTA (PROVISIONAL DISTRICT)",
            ("Library of Parliament, Related", "Ontario", "BARRIE--SIMCOE"): SkippedObject,
            ("Library of Parliament, Related", "Ontario", "BRAMPTON--HALTON HILLS"): SkippedObject,
            ("Library of Parliament, Related", "Ontario", "DUFFERIN--WELLINGTON"): SkippedObject,
            ("Library of Parliament, Related", "Ontario", "LANARK--FRONTENAC"): SkippedObject,
            ("Library of Parliament, Related", "Ontario", "LONDON--ADELAIDE"): SkippedObject,
            ("Library of Parliament, Related", "Ontario", "NORTHUMBERLAND--PINE RIDGE"): SkippedObject,
            ("Library of Parliament, Related", "Ontario", "PEEL--DUFFERIN"): SkippedObject,
            ("Library of Parliament, Related", "Ontario", "KITCHENER--WILMOT--WELLESLEY--WOOLWICH"): SkippedObject,
            ("Library of Parliament, Related", "Ontario", "VAUGHAN--AURORA"): SkippedObject,
            ("Library of Parliament, Related", "Quebec", "BELLECHASSE--MONTMAGNY--L'ISLET"): SkippedObject,
            ("Library of Parliament, Related", "Quebec", "BLAINVILLE"): SkippedObject,
            ("Library of Parliament, Related", "Quebec", "BOUCHER--LES PATRIOTES--VERCHÈRES"): SkippedObject,
            ("Library of Parliament, Related", "Quebec", "LAFONTAINE--ROSEMONT"): SkippedObject,
            ("Library of Parliament, Related", "Quebec", "DEUX-MONTAGNES"): SkippedObject,
            ("Library of Parliament, Related", "Quebec", "DORVAL--LACHINE"): SkippedObject,
            ("Library of Parliament, Related", "Quebec", "GASPÉ--BONAVENTURE--ÎLES-DE-LA-MADELEINE"): SkippedObject,
            ("Library of Parliament, Related", "Quebec", "KAMOURASKA--RIVIÈRE-DU-LOUP--TÉMISCOUATA"): SkippedObject,
            ("Library of Parliament, Related", "Quebec", "LACHINE--NOTRE-DAME-DE-GRÂCE"): SkippedObject,
            ("Library of Parliament, Related", "Quebec", "LASALLE--VERDUN"): SkippedObject,
            ("Library of Parliament, Related", "Quebec", "LEMOYNE"): SkippedObject,
            ("Library of Parliament, Related", "Quebec", "VILLE-MARIE"): SkippedObject,
            ("Library of Parliament, Related", "Saskatchewan", "ASSINIBOIA EAST"): SkippedObject,
            ("Library of Parliament, Related", "Saskatchewan", "ASSINIBOIA WEST"): SkippedObject,
            ("Library of Parliament, Related", "Saskatchewan", "CALGARY"): SkippedObject,
            ("Library of Parliament, Related", "Saskatchewan", "EDMONTON"): SkippedObject,
            ("Library of Parliament, Related", "Saskatchewan", "HUMBOLDT--WARMAN--MARTENSVILLE--ROSETOWN"): SkippedObject,
            ("Library of Parliament, Related", "Saskatchewan", "REGINA--ARM RIVER"): SkippedObject,
            ("Library of Parliament, Related", "Saskatchewan", "SASKATCHEWAN"): SkippedObject,
            ("Library of Parliament, Related", "Saskatchewan", "SASKATOON--ROSETOWN"): SkippedObject,
            ("Library of Parliament, Related", "Saskatchewan", "STRATHCONA"): SkippedObject,
            ("Parliament, Constituencies", "Nova Scotia", "South Shore—St. Margarets"): "SOUTH SHORE--ST. MARGARETS",
            ("Parliament, Chamber Vote Detail", "Nova Scotia", "South Shore—St. Margarets"): "SOUTH SHORE--ST. MARGARETS",
            ("Parliament, Chamber Vote Detail", "Quebec", "Mount Royal"): ["MONT ROYAL", "MOUNT ROYAL"],
            ("Parliament, Chamber Vote Detail", "Northwest Territories", "Northwest Territories"): ["NORTHWEST TERRITORIES", "WESTERN ARCTIC"],
            ("Wikipedia", "British Columbia", "Cariboo District"): "Cariboo",
            ("Wikipedia", "British Columbia", "New Westminster District"): "New Westminster",
            ("Wikipedia", "British Columbia", "Westminster"): "Westminster District",
            ("Wikipedia", "British Columbia", "Yale District"): "Yale",
            ("Wikipedia", "Ontario", "City of Ottawa"): "Ottawa (City of)",
            ("Wikipedia", "Ontario", "County of Ottawa"): "Ottawa (County of)",
            ("Wikipedia", "Quebec", "County of Ottawa"): "Ottawa (County of)",
            ("Wikipedia", "Quebec", "Town of Sherbrooke"): "Sherbrooke (Town of)",
            ("Wikipedia", "Saskatchewan", "Calgary"): SkippedObject,
            ("Wikipedia", "Saskatchewan", "Edmonton"): SkippedObject,
            ("Wikipedia", "Saskatchewan", "Saskatchewan"): SkippedObject,
            ("Wikipedia", "Saskatchewan", "Strathcona"): SkippedObject,
        }.get((kwargs["search_name_source"], kwargs["province"].name, kwargs["name"]), None)
    if kwargs["search_name_source"] == "Wikipedia" and kwargs["name"] in (
        "Alberta (Provisional District)",
        "Regina—Qu'Appelle",
        "Assiniboia West",
        "Assiniboia East",
    ):
        kwargs.pop("province")
    return get_object(models.Riding, *args, **kwargs)




def get_parliamentarian(*args, **kwargs):
    name = TITLE_REGEX.sub("", kwargs["name"])
    if "search_name_corrected" not in kwargs and kwargs["search_name_source"] == "OpenParliament.ca":
        try:
            kwargs["search_name_corrected"] = {
                ("Quebec", "Paul Martin"): "MARTIN, Paul (2)",
                ("Quebec", "Marcel Massé"): "MASSÉ, Marcel (2)",
                ("New Brunswick", "John Herron"): "HERRON, John (2)",
                ("Ontario", "John Finlay"): "FINLAY, John (2)",
                ("British Columbia", "David A. Anderson"): "ANDERSON, David",
                ("British Columbia", "David Anderson"): "ANDERSON, David",
                ("Saskatchewan", "David Anderson"): "ANDERSON, David (2)",
            }[(
                kwargs["election_candidates__election_riding__riding__province"].name,
                name,
            )]
        except KeyError:
            pass
    if "search_name_corrected" not in kwargs:
        try:
            kwargs["search_name_corrected"] = {
                "Alexander Nuttall": "NUTTALL, Alex",
                "Alfonso L. Gagliano": "GAGLIANO, Alfonso",
                "Alupa A. Clarke": "CLARKE, Alupa",
                "Benoît Serré": "SERRÉ, Ben",
                "Bobby Morrissey": "MORRISSEY, Robert",
                "Bradley Trost": "TROST, Bradley R.",
                "Catherine McKenna": "MCKENNA, Catherine Mary",
                "David A. Anderson": "ANDERSON, David",
                "David J. McGuinty": "MCGUINTY, David",
                "David de Burgh Graham": "GRAHAM, David",
                "Deborah Schulte": "SCHULTE, Deb",
                "Dianne L. Watts": "WATTS, Dianne Lynn",
                "Eric Lowther": "LOWTHER, Eric C.",
                "Fred Mifflin": "MIFFLIN, Fred J.",
                "Glen Douglas Pearson": "PEARSON, Glen",
                "Gordon Brown": "BROWN, Gord",
                "Greg Francis Thompson": "THOMPSON, Greg",
                "Guy Arseneault": "ARSENEAULT, Guy H.",
                "Jake Hoeppner": "HOEPPNER, Jake E.",
                "Jean R. Rioux": "RIOUX, Jean",
                "Jean-Claude D'Amours": "D'AMOURS, Jean-Claude JC",
                "Jinny Jogindera Sims": "SIMS, Jinny",
                "John G. Williams": "WILLIAMS, John",
                "Judy A. Sgro": "SGRO, Judy",
                "K. Kellie Leitch": "LEITCH, Kellie",
                "Karen Vecchio": "VECCHIO, Karen Louise",
                "Kerry-Lynne D. Findlay": "FINDLAY, Kerry-Lynne",
                "Khristinn Kellie Leitch": "LEITCH, Kellie",
                "LAFLAMME, J.-Léo-K.": "LAFLAMME, Léo Kemner",
                "Louise Hardy": "HARDY, Louise Frances",
                "M.P. Tom Wappel": "WAPPEL, Tom",
                "Marc Serré": "SERRÉ, Marc G",
                "Megan Anissa Leslie": "LESLIE, Megan",
                "Michael Chong": "CHONG, Mike",
                "Michael D. Chong": "CHONG, Mike",
                "Michael V. McLeod": "MCLEOD, Michael",
                "Michel Picard": "PICARD, Michel",
                "Neil R. Ellis": "ELLIS, Neil",
                "Ovid Jackson": "JACKSON, Ovid L.",
                "Patricia Davidson": "DAVIDSON, Pat",
                "Peter MacKay": "MACKAY, Peter G.",
                "Rhéal Éloi Fortin": "FORTIN, Rhéal",
                "Richard Harris": "HARRIS, Dick",
                "Richard M. Harris": "HARRIS, Dick",
                "Robert D. Nault": "NAULT, Bob",
                "Robert J. Morrissey": "MORRISSEY, Robert",
                "Robert Kitchen": "KITCHEN, Robert Gordon",
                "Robert Nault": "NAULT, Bob",
                "Robert Oliphant": "OLIPHANT, Rob",
                "Ronald Duhamel": "DUHAMEL, Ronald J.",
                "Roy Bailey": "BAILEY, Roy H.",
                "Ruben Efford": "EFFORD, R. John",
                "Ruben John Efford": "EFFORD, R. John",
            }[name]
        except KeyError:
            name_split = name.split()
            kwargs["search_name_corrected"] = [
                ", ".join(filter(None, reversed((
                    " ".join(name_split[:position]),
                    " ".join(name_split[position:]),
                ))))
                for position in range(len(name_split))
            ]
    return get_object(models.Parliamentarian, *args, **kwargs)

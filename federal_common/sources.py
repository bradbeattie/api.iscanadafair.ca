import re

EN = "EN"
FR = "FR"

NAME_CANADIANA = {EN: "Canadian Parliamentary Historical Resources", FR: "Ressources parlementaires historiques canadiennes"}
NAME_EC = {EN: "Elections Canada", FR: "Élections Canada"}
NAME_EC_FAQ = {EN: "Elections Canada, FAQ", FR: "Élections Canada, Questions et réponses"}
NAME_EC_MAP = {EN: "Elections Canada, Map", FR: "Élections Canada, Carte"}
NAME_EC_PROFILE = {EN: "Elections Canada, Profile", FR: "Élections Canada, Profil"}
NAME_EC_SHORT = {EN: "Elections Canada, Short", FR: "Élections Canada, Bref"}
NAME_HOC = {EN: "House of Commons", FR: "Chambre des communes"}
NAME_HOC_CONSTITUENCIES = {EN: "House of Commons, Constituencies", FR: "Chambre des communes, Circonscriptions"}
NAME_HOC_HANSARD_XML = {EN: "House of Commons, Hansard XML", FR: "Chambre des communes, Hansard XML"}
NAME_HOC_MEMBERS = {EN: "House of Commons, Members", FR: "Chambre des communes, Députés"}
NAME_HOC_VOTES = {EN: "House of Commons, Votes", FR: "Chambre des communes, Votes"}
NAME_HOC_VOTE_DETAILS = {EN: "House of Commons, Vote Details", FR: "Chambre des communes, Détails du vote"}
NAME_LEGISINFO = {EN: "LEGISinfo", FR: "LEGISinfo"}
NAME_LEGISINFO_NUMBER = {EN: "LEGISinfo, Number", FR: "LEGISinfo, Numéro"}
NAME_LEGISINFO_TITLE = {EN: "LEGISinfo, Title", FR: "LEGISinfo, Titre"}
NAME_LEGISINFO_TITLE_SHORT = {EN: "LEGISinfo, Short Title", FR: "LEGISinfo, Titre abrégé"}
NAME_LOP_BY_ELECTION = {EN: "Library of Parliament, By-Elections", FR: "Bibliothèque du Parlement, Élections partielles"}
NAME_LOP_GENERAL_ELECTION = {EN: "Library of Parliament, General Elections", FR: "Bibliothèque du Parlement, Élections générales"}
NAME_LOP_PARLIAMENT = {EN: "Library of Parliament, Parliament File", FR: "Bibliothèque du Parlement, Fiche de législature"}
NAME_LOP_PARLIAMENTARIAN = {EN: "Library of Parliament, Parliamentarian File", FR: "Bibliothèque du Parlement, Fiche de parlementaire"}
NAME_LOP_PARTY = {EN: "Library of Parliament, Party File", FR: "Bibliothèque du Parlement, Fiche de parti politique"}
NAME_LOP_PARTY_SHORT = {EN: "Library of Parliament, Short", FR: "Bibliothèque du Parlement, Bref"}
NAME_LOP_PROVINCE = {EN: "Library of Parliament, Province / Territory File", FR: "Bibliothèque du Parlement, Fiche de province / territoire"}
NAME_LOP_RIDING_HISTORY = {EN: "Library of Parliament, History of Federal Ridings", FR: "Bibliothèque du Parlement, Historique des circonscriptions"}
NAME_OP = {EN: "OpenParliament.ca", FR: "OpenParliament.ca"}
NAME_PARLVU = {EN: "ParlVU", FR: "ParlVU"}
NAME_PARLVU_DESCRIPTION = {EN: "ParlVU, Description", FR: "ParlVU, Description"}
NAME_PARLVU_TITLE = {EN: "ParlVU, Title", FR: "ParlVU, Titre"}
NAME_PARL_COMMITTEE = {EN: "Parliament of Canada, Committees", FR: "Parlement du Canada, Comités"}
NAME_PARL_COMMITTEE_CODE = {EN: "Parliament of Canada, Committees, Short", FR: "Parlement du Canada, Comités, Bref"}
NAME_TWITTER = {EN: "Twitter", FR: "Twitter"}
NAME_WIKI = {EN: "Wikipedia", FR: "Wikipédia"}

LANG_CANADIANA_CONTENT = {EN: "eng", FR: "fra"}
LANG_CANADIANA_UI = LANG_LEGISINFO_XML = LANG_WIKI = LANG_PARLVU = {EN: "en", FR: "fr"}
LANG_LOP = LANG_LEGISINFO_UI = LANG_HOC_HANSARD_XML = {EN: "E", FR: "F"}
LANG_EC = {EN: "e", FR: "f"}

AVAILABILITY_WARNINGS = re.compile(r" \((Disponible en anglais seulement|Available in French only)\)")
LOP_CODE = re.compile("([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", re.I)
LOP_RIDING_AND_PROVINCE = re.compile("^(?P<riding>.*)\s+\((?P<province>.*)\)$")
WHITESPACE = re.compile("\s+")

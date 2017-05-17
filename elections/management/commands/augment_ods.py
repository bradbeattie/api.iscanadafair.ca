from django.core.management.base import BaseCommand
from django.db import transaction
from elections import models
from elections import get_by_name_variant
from pyexcel_ods import get_data
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument("ods file")

    def handle(self, *args, **options):
        if options["verbosity"] > 1:
            logger.setLevel(logging.DEBUG)

        logger.info("Augment with ODS data")
        self.augment_ridings_ods(get_data(options["ods file"]))

    def augment_ridings_ods(self, riding_data):
        logger.info("Augmenting ridings")
        for election_number, sheet in riding_data.items():
            general_election = models.GeneralElection.objects.get(number=election_number)
            print(general_election, "Riding data")
            for row in sheet[1:]:
                self.augment_ridings_election(general_election, *row)

    @transaction.atomic
    def augment_ridings_election(self, general_election, province_name, riding_name, population, registered, ballots_rejected):
        search_name_source = "Elections Canada, {}".format(general_election)
        province = get_by_name_variant.get_province(
            name=province_name.strip(),
            search_name_source=search_name_source,
        )
        riding = get_by_name_variant.get_riding(
            province=province,
            election_ridings__general_election=general_election,
            name=riding_name.strip(),
            search_name_source=search_name_source,
        )
        election_riding = models.ElectionRiding.objects.get(
            general_election=general_election,
            riding=riding,
        )
        election_riding.population = population
        election_riding.registered = registered
        election_riding.ballots_rejected = ballots_rejected
        election_riding.save()

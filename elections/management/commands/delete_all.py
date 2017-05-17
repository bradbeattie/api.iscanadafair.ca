from django.core.management.base import BaseCommand
from django.db.models.base import ModelBase
from elections import models
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def handle(self, *args, **options):
        logger.info("Deleting all models")
        for model_name in dir(models):
            if not model_name.startswith("_") and model_name[0].isupper():
                model = getattr(models, model_name)
                if isinstance(model, ModelBase):
                    logger.debug("Deleting all {}".format(model))
                    model.objects.all().delete()

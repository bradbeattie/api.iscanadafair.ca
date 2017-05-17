from elections import models
from rest_framework import serializers


class ElectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Election
        fields = '__all__'

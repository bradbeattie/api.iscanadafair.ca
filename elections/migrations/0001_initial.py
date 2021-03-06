# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-06-30 02:31
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import django_extensions.db.fields.json


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('parliaments', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ByElection',
            fields=[
                ('slug', models.SlugField(max_length=200, primary_key=True, serialize=False)),
                ('date', models.DateField(db_index=True)),
                ('links', django_extensions.db.fields.json.JSONField(default=dict)),
                ('parliament', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='by_elections', to='parliaments.Parliament')),
            ],
            options={
                'ordering': ('date',),
            },
        ),
        migrations.CreateModel(
            name='ElectionCandidate',
            fields=[
                ('slug', models.SlugField(max_length=200, primary_key=True, serialize=False)),
                ('name', models.CharField(db_index=True, max_length=200)),
                ('profession', models.CharField(db_index=True, max_length=200)),
                ('ballots', models.PositiveIntegerField(db_index=True, null=True)),
                ('ballots_percentage', models.DecimalField(db_index=True, decimal_places=3, help_text='Aggregate', max_digits=4, null=True)),
                ('elected', models.BooleanField(db_index=True)),
                ('acclaimed', models.BooleanField(db_index=True)),
            ],
            options={
                'ordering': ('election_riding__date', 'election_riding__riding__slug', 'name'),
            },
        ),
        migrations.CreateModel(
            name='ElectionRiding',
            fields=[
                ('slug', models.SlugField(max_length=200, primary_key=True, serialize=False)),
                ('date', models.DateField(db_index=True)),
                ('ballots_rejected', models.PositiveIntegerField(db_index=True, null=True)),
                ('registered', models.PositiveIntegerField(db_index=True, null=True)),
                ('population', models.PositiveIntegerField(db_index=True, null=True)),
                ('by_election', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='election_ridings', to='elections.ByElection')),
            ],
            options={
                'ordering': ('date', 'riding__slug'),
            },
        ),
        migrations.CreateModel(
            name='GeneralElection',
            fields=[
                ('number', models.PositiveSmallIntegerField(primary_key=True, serialize=False)),
                ('date_fuzz', models.DateField(db_index=True, help_text='TODO: Explain date problems')),
                ('date', models.DateField(db_index=True)),
                ('returns', models.URLField()),
                ('population', models.PositiveIntegerField(db_index=True, help_text='Aggregate')),
                ('registered', models.PositiveIntegerField(db_index=True, help_text='Aggregate')),
                ('ballots_total', models.PositiveIntegerField(db_index=True, help_text='Aggregate, includes rejected ballots')),
                ('turnout', models.DecimalField(db_index=True, decimal_places=3, help_text='Aggregate', max_digits=3)),
                ('links', django_extensions.db.fields.json.JSONField(default=dict)),
                ('wiki_info_box', django_extensions.db.fields.json.JSONField(default=dict)),
                ('parliament', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='general_election', to='parliaments.Parliament')),
            ],
            options={
                'ordering': ('date',),
            },
        ),
        migrations.AddField(
            model_name='electionriding',
            name='general_election',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='election_ridings', to='elections.GeneralElection'),
        ),
        migrations.AddField(
            model_name='electionriding',
            name='riding',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='election_ridings', to='parliaments.Riding'),
        ),
        migrations.AddField(
            model_name='electioncandidate',
            name='election_riding',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='election_candidates', to='elections.ElectionRiding'),
        ),
        migrations.AddField(
            model_name='electioncandidate',
            name='parliamentarian',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='election_candidates', to='parliaments.Parliamentarian'),
        ),
        migrations.AddField(
            model_name='electioncandidate',
            name='party',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='election_candidates', to='parliaments.Party'),
        ),
        migrations.AlterIndexTogether(
            name='electionriding',
            index_together=set([('general_election', 'riding'), ('by_election', 'riding')]),
        ),
    ]

#!/bin/bash
./manage.py check && \
flake8 --ignore E501 parliaments proceedings elections localsite && \
mysql -e "DROP DATABASE parliamentary_data" && \
mysql -e "CREATE DATABASE parliamentary_data CHARACTER SET utf8 COLLATE utf8_general_ci" && \
rm -rf parliaments/migrations && \
rm -rf proceedings/migrations && \
rm -rf elections/migrations && \
./manage.py makemigrations parliaments && \
./manage.py makemigrations proceedings && \
./manage.py makemigrations elections && \
./manage.py migrate && \
echo "from django.contrib.auth.models import User; User.objects.create_superuser('admin', 'admin@example.com', 'pass')" | python manage.py shell &&
mysqldump parliamentary_data > after-step-0.sql

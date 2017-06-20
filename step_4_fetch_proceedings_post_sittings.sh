#!/bin/bash
./manage.py check && \
flake8 --ignore E501 parliaments proceedings elections localsite && \
mysql parliamentary_data < after-step-3.sql && \
./manage.py fetch_recordings && \
./manage.py fetch_house_votes && \
./manage.py fetch_hansards && \
mysqldump parliamentary_data > after-step-4.sql

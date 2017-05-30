#!/bin/bash
./manage.py check && \
flake8 --ignore E501 parliaments proceedings elections localsite && \
mysql parliamentary_data < after-step-2.sql && \
./manage.py fetch_committees && \
./manage.py fetch_bills && \
./manage.py fetch_sittings && \
#./manage.py fetch_recordings && \
#./manage.py fetch_house_votes && \
mysqldump parliamentary_data > after-step-3.sql

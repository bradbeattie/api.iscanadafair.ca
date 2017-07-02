#!/bin/bash
mysqldump parliamentary_data $(mysql -D parliamentary_data -Bse "show tables WHERE Tables_in_parliamentary_data REGEXP '^(parliaments|elections|proceedings)_'") > deployed.sql
rm deployed.sql.xz
xz deployed.sql

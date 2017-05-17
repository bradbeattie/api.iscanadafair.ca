#!/bin/bash
mysqldump elections $(mysql -D elections -Bse "show tables like 'elections_%'") > populated.sql
xz -9 populated.sql
XZ_OPT=-9 tar cJfv photos.tar.xz photos
XZ_OPT=-9 tar cJfv urlcache.tar.xz urlcache

cat ./step_0_wipe.sh && time ./step_0_wipe.sh && \
cat ./step_1_fetch_parliaments_and_elections.sh && time ./step_1_fetch_parliaments_and_elections.sh && \
cat ./step_2_augment_parliaments_and_elections.sh && time ./step_2_augment_parliaments_and_elections.sh && \
cat ./step_3_fetch_proceedings.sh && time ./step_3_fetch_proceedings.sh && \
./dump.sh

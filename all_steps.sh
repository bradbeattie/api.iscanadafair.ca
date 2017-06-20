cat ./step_0_wipe.sh && time ./step_0_wipe.sh && \
cat ./step_1_fetch_parliaments_and_elections.sh && time ./step_1_fetch_parliaments_and_elections.sh && \
cat ./step_2_augment_parliaments_and_elections.sh && time ./step_2_augment_parliaments_and_elections.sh && \
cat ./step_3_fetch_proceedings_pre_sittings.sh && time ./step_3_fetch_proceedings_pre_sittings.sh && \
cat ./step_4_fetch_proceedings_post_sittings.sh && time ./step_4_fetch_proceedings_post_sittings.sh && \
./dump.sh

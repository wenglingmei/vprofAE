#generate variabel meta data
./generate_meta.sh
#run norm case
./run_norm.sh
sleep 20
#run buggy case
./run_bug.sh
sleep 20
#post profiling analysis
./analyze.sh

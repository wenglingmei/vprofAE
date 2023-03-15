#run test case
cd redis-8145-test
cwd=`pwd`
vprofAE=$cwd/../../
#analyze data
cd $cwd
mkdir -p result
python3 $vprofAE/PostProfilingAnalysis/vprof_profile.py --norms norms/ --bugs bugs/ --bug_bin ./redis/src/redis-server --norm_bin ./redis/src/redis-server --max 5 > result/vprof_profile.txt

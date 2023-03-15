#run test case
cd redis-8145-test
cwd=`pwd`
vprofAE=$cwd/../../
#analyze data
cd $cwd
mkdir -p result
python3 $vprofAE/PostProfilingAnalysis/vprof_profile.py --norms norms/ --bugs bugs/ --bug_bin ./redis/src/redis-server --norm_bin ./redis/src/redis-server --max 5 --index 0 > result/vprof_profile_0.txt
python3 $vprofAE/PostProfilingAnalysis/vprof_profile.py --norms norms/ --bugs bugs/ --bug_bin ./redis/src/redis-server --norm_bin ./redis/src/redis-server --max 5 --index 1 > result/vprof_profile_1.txt
python3 $vprofAE/PostProfilingAnalysis/vprof_profile.py --norms norms/ --bugs bugs/ --bug_bin ./redis/src/redis-server --norm_bin ./redis/src/redis-server --max 5 --index 2 > result/vprof_profile_2.txt
python3 $vprofAE/PostProfilingAnalysis/vprof_profile.py --norms norms/ --bugs bugs/ --bug_bin ./redis/src/redis-server --norm_bin ./redis/src/redis-server --max 5 --index 3 > result/vprof_profile_3.txt
python3 $vprofAE/PostProfilingAnalysis/vprof_profile.py --norms norms/ --bugs bugs/ --bug_bin ./redis/src/redis-server --norm_bin ./redis/src/redis-server --max 5 --index 4 > result/vprof_profile_4.txt

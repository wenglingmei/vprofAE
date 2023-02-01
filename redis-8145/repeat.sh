cd redis-8145-test
cwd=`pwd`
vprofAE=$cwd/../../

#run anomaly test cases
mkdir -p /tmp/vprof/gmon
mkdir -p /tmp/vprof/gmon_var
mkdir -p /tmp/vprof/layout

cp ../19-cluster-node-slots.bug.tcl ./redis/tests/cluster/tests/19-cluster-node-slots.tcl
cd ./redis/tests/cluster
LD_PRELOAD=$vprofAE/glibcForPRELOAD/glibc-2.31/build/install/lib/libc.so.6 tclsh run_bug.tcl
echo "kill sigusr2"
sudo kill -SIGUSR2 `pidof redis-server`

#save anomaly test data
cd $cwd
rm -rf bugs
mkdir bugs

mv /tmp/vprof/gmon bugs/
mv /tmp/vprof/gmon_var bugs/
mv /tmp/vprof/layout bugs/
cp src2bb.txt bugs/
echo "killall"
sudo killall redis-server

#analyze data
cd $cwd
mkdir -p result
python $vprofAE/PostProfilingAnalysis/vprof_profile.py --norms norms/ --bugs bugs/ --bug_bin ./redis/src/redis-server --norm_bin ./redis/src/redis-server > result/vprof_profile.txt

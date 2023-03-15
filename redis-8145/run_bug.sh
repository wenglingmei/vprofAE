#run test case
sudo sysctl -w fs.file-max=65000
ulimit -S -n 16384
mkdir -p redis-8145-test
mkdir -p /tmp/vprof
cd redis-8145-test
cwd=`pwd`
vprofAE=$cwd/../../

if [ ! -f "$vprofAE/glibcForPRELOAD/glibc-2.31/build/install/lib/libc.so.6" ]; then
  echo "$vprofAE/glibcForPRELOAD/glibc-2.31/build/install/lib/libc.so.6 does not exist."
  exit 1
fi

cp ../instances.tcl ./redis/tests/
cp ../run_bug.tcl ./redis/tests/cluster/
cp ../19-cluster-node-slots.bug.tcl ./redis/tests/cluster/tests/

rm /tmp/vprof/info.txt
ln -s $cwd/redis-8145.meta  /tmp/vprof/info.txt

if [ ! -f "/tmp/vprof/info.txt" ]; then
  echo "/tmp/vprof/info.txt does not exist."
  exit 1
fi

#run bug test cases
rm -rf /tmp/vprof/gmon
rm -rf /tmp/vprof/gmon_var
rm -rf /tmp/vprof/layout
mkdir -p /tmp/vprof/gmon
mkdir -p /tmp/vprof/gmon_var
mkdir -p /tmp/vprof/layout

cd ./redis/tests/cluster
LD_PRELOAD=$vprofAE/glibcForPRELOAD/glibc-2.31/build/install/lib/libc.so.6 tclsh run_bug.tcl
echo "kill sigusr2"
sudo kill -SIGUSR2 `pidof redis-server`

#save anomaly test data
cd $cwd
rm -rf bugs
mkdir -p  bugs
mv /tmp/vprof/gmon bugs/
mv /tmp/vprof/gmon_var bugs/
mv /tmp/vprof/layout bugs/
cp src2bb.txt bugs/
echo "killall"
sudo kill -9 `pidof redis-server`

##analyze data
#cd $cwd
#mkdir -p result
#python $vprofAE/PostProfilingAnalysis/vprof_profile.py --norms norms/ --bugs bugs/ --bug_bin ./redis/src/redis-server --norm_bin ./redis/src/redis-server > result/vprof_profile.txt

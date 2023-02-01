#run test case
mkdir redis-8145-test
cd redis-8145-test
cwd=`pwd`
vprofAE=$cwd/../../

#download redis
git clone https://github.com/redis/redis.git
cd redis
git checkout e288430c05359706bcb0f78730af2997ab0db07f -b 8145

#build redis for schema and static analysis
export SchemaComponent=cluster.c
mkdir -p /tmp/vprof
make distclean
CC=/usr/local/opt/llvm/bin/clang CXX=/usr/local/opt/llvm/bin/clang++ make CFLAGS="-fno-stack-protector -g -flegacy-pass-manager -Xclang -load -Xclang $vprofAE/LLVMPassSchemaGen/build/ProfileVar/libProfileVarPass.so -pg -O2" LDFLAGS="-fno-stack-protector -g -flegacy-pass-manager -Xclang -load -Xclang $vprofAE/LLVMPassSchemaGen/build/ProfileVar/libProfileVarPass.so -pg -O2"
mv /tmp/vprof/schema.txt ../
mv /tmp/vprof/src2bb.txt ../

#build redis for production run
make distclean
make CFLAGS="-pg -O2" LDFLAGS="-pg -O2"

#goto redis-8145-test to translate schema into metadata
cd $cwd
python $vprofAE/LLVMPassSchemaGen/translate_schema_multiprocessing.py --elf ./redis/src/redis-server --schema ./schema.txt --exec redis-server --out redis-8145.meta

#link metadata to glibc
#rm $vprofAE/glibcForPRELOAD/glibc-2.31/build/info.txt
rm /tmp/vprof/info.txt
ln -s $cwd/redis-8145.meta  /tmp/vprof/info.txt

cp ../instances.tcl ./redis/tests/
cp ../run_norm.tcl ./redis/tests/cluster/
cp ../run_bug.tcl ./redis/tests/cluster/

#run normal test cases
mkdir -p /tmp/vprof/gmon
mkdir -p /tmp/vprof/gmon_var
mkdir -p /tmp/vprof/layout

cp ../19-cluster-node-slots.norm.tcl ./redis/tests/cluster/tests/19-cluster-node-slots.tcl
cd ./redis/tests/cluster
LD_PRELOAD=$vprofAE/glibcForPRELOAD/glibc-2.31/build/install/lib/libc.so.6 tclsh run_norm.tcl
echo "kill sigusr2"
sudo kill -SIGUSR2 `pidof redis-server`

#save normal test data
cd $cwd
rm -rf norms
mkdir -p norms
mv /tmp/vprof/gmon norms/
mv /tmp/vprof/gmon_var norms/
mv /tmp/vprof/layout norms/
cp src2bb.txt norms/
echo "killall"
sudo killall redis-server
sleep 20

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
sleep 20

#analyze data
cd $cwd
mkdir -p result
python $vprofAE/PostProfilingAnalysis/vprof_profile.py --norms norms/ --bugs bugs/ --bug_bin ./redis/src/redis-server --norm_bin ./redis/src/redis-server > result/vprof_profile.txt

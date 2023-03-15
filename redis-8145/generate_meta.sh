#run test case
rm -rf redis-8145-test
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
rm -rf /tmp/vprof
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

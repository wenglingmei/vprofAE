#download vprof
#git clone https://github.com/wenglingmei/vprofAE.git
#cd vprofAE
pwd=$PWD

#prepare glibc
cd glibcForPRELOAD
source ./build_glibc.sh
wait

#prepare compilation LLVMPass
#pre-requites: build llvm into LLVM_DIR, e.g. /usr/loca/opt/llvm
cd $pwd/LLVMPassSchemaGen
mkdir build
cd build
LLVM_DIR=/usr/local/opt/llvm cmake ..
make
cd $pwd

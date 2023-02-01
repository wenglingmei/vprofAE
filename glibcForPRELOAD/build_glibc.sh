cd glibc-2.31
#build clean glibc
mkdir build
cd build
../configure --prefix `pwd`/install
make -j 12 && make install
#apply patch and build over the clean version
cd ..
patch -p1 < ../glibc-2.31.patch
cd build
make -j 12 && make install
#restore effected libraries other than libc
cd install/lib
pwd
rm libcrypt.so.1
ln -s /usr/lib/x86_64-linux-gnu/libcrypt.so.1 libcrypt.so.1
rm libpthread-2.31.so
rm libpthread.so.0
ln -s /usr/lib/x86_64-linux-gnu/libpthread-2.31.so libpthread-2.31.so
ln -s libpthread-2.31.so libpthread.so.0
ln -s /usr/lib/x86_64-linux-gnu/libunwind.so.8 libunwind.so.8
ln -s /usr/lib/x86_64-linux-gnu/liblzma.so.5 liblzma.so.5
ln -s /usr/lib/locale locale
pwd
cd ../../nptl
mv libpthread.so libpthread.so.bak
ln -s /usr/lib/x86_64-linux-gnu/libpthread.so libpthread.so
#test usable of locale
../install/bin/locale -a
pwd

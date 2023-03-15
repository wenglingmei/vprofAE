# Effective Performance Issue Diagnosis with Value-Assisted Cost Profiling

Diagnosing performance issues is often difficult, especially when they
occur only during some program executions.
Profilers can help with performance debugging, but are ineffective
when the most costly functions are not the root causes of performance
issues.  To address this problem, we
introduce a new profiling methodology,
**value-assisted cost profiling**, and a tool vprof.
Our insight is that capturing the values of variables can
greatly help diagnose performance issues.
vprof continuously records values while profiling normal and buggy
program executions.  It identifies anomalies in the values and
the functions where they occur to pinpoint the real root causes of
performance issues.

## Download the directory
```
git clone git@github.com:wenglingmei/vprofAE.git
```
## Install software dependencies

install llvm-project
```
$ git clone https://github.com/llvm/llvm-project.git
$ cd llvm-project
$ cmake -S llvm -B build -G "Unix Makefiles" -DLLVM_ENABLE_PROJECTS="clang;lld" -DCMAKE_BUILD_TYPE=Release
$ cmake --build .
```
install libunwind
```
$ git clone https://github.com/libunwind/libunwind.git
$ cd libunwind
$ autoreconf -i
$ ./configure
$ make
$ make install
```
install pytelftools
```
$ pip install pyelftools
```
## Create a soft link from llvm-project/build to /usr/local/opt/llvm
```
$ ln -s llvm-project/build /usr/local/opt/llvm
```
## Setup vprof
```
$./prepare.sh
```
## Run testcase.
```
$ cd redis-8145
$./test.sh
```
# Reference
Effective Performance Issue Diagnosis with Value-Assisted Cost Profiling (Eurosys'23)

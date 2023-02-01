# vprofAE

1. install software dependencies
```
install llvm-project

install libunwind
```
2.create a soft link from llvm-project/build to /usr/local/opt/llvm
```
$ln -s llvm-project/build /usr/local/opt/llvm
```
3.setup vprof
```
$./prepare.sh
```
4.run testcase.
```
$ cd redis-8145
$./test.sh
```

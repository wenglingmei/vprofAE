# Pre-requites
 build llvm into LLVM\_DIR

# Build:  
```
  $ mkdir build 
  $ cd build
  $ LLVM_DIR=/usr/local/opt/llvm cmake ..
  $ make
```
# Run example:
```
  $ /usr/local/opt/llvm/bin/clang -g -flegacy-pass-manager -Xclang -load -Xclang /path/to/LLVMPassSchemaGen/build/ProfileVar/libProfileVarPass.so /path/to/example.c
```
# Select component for schema generation:
```
  $ set env SchemaComponent=[path/filename]#partial matching during compilation
```

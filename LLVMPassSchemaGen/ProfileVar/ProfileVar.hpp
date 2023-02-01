#ifndef ProfileVar_HPP
#define ProfileVar_HPP
#include "llvm/Pass.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/BasicBlock.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/InstrTypes.h"
#include "llvm/IR/IntrinsicInst.h"
#include "llvm/IR/LegacyPassManager.h"
#include "llvm/IR/DataLayout.h"
#include "llvm/IR/DebugLoc.h"
#include "llvm/IR/DebugInfoMetadata.h"
#include "llvm/Support/raw_ostream.h"
#include "llvm/AsmParser/LLToken.h"
#include "llvm/Transforms/IPO/PassManagerBuilder.h"
#include "llvm/ADT/DenseMap.h"
#include "llvm/ADT/GraphTraits.h"
#include "llvm/ADT/iterator.h"
#include "llvm/ADT/SCCIterator.h"
#include "llvm/Analysis/CallGraphSCCPass.h"
#include "llvm/Analysis/CallGraph.h"
#include "llvm/Analysis/LoopInfo.h"
#include "llvm/Analysis/LoopInfoImpl.h" 
#include "llvm/Analysis/ScalarEvolution.h"
#include "llvm/Analysis/ScalarEvolutionExpressions.h"
#include "llvm/Demangle/Demangle.h"
#include "llvm/IR/Operator.h"

#include <set>
#include <map>
#include <vector>
#include <fstream>
#include <cstdarg>
using namespace llvm;

class ValueEdge{
public:
  Value *src;
  Value *dst;
  Function *F;
  ValueEdge(Value *dst_, Value *src_, Function *F_)
    :src(src_), dst(dst_), F(F_) {}
};

void Log(const char*path, const char *fmt, ...);
std::string instDesc(Instruction *I);
std::string valDesc(Value *v);
void SaveBlockInfo(const BasicBlock *bb);
void SaveFunctionInfo(const Function *f);
Function *search(std::unordered_map<Value *, std::vector<ValueEdge> > &dst_edges, Value *dst);
void valueFlowInFunction(Function *F, std::unordered_map<Value *, MDNode *> vals);

#define SCHEMA_FILE "/tmp/vprof/schema.txt"
#define SRC2BB_FILE "/tmp/vprof/src2bb.txt"

#ifdef SCHEMA_FILE
/*save schema to file*/
#define LogSchema(fmt, ...) Log(SCHEMA_FILE, fmt, ##__VA_ARGS__)
#else
#define LogSchema(fmt, ...) do{}while(0)
#endif

#ifdef SRC2BB_FILE
#define LogSrc2bb(fmt, ...) Log(SRC2BB_FILE, fmt, ##__VA_ARGS__)
#else
#define LogSrc2bb(fmt, ...) do{}while(0)
#endif


namespace {
  class ProfileVarPass : public ModulePass {
  public:
    static char ID;
    std::unordered_map<Function*, int> FuncMap;
    std::set<GlobalValue*> Globals;

    ProfileVarPass() : ModulePass(ID) {}
    void getAnalysisUsage(AnalysisUsage &AU) const override;
    virtual bool runOnModule(Module& m) override;
    std::string getEnv(const char *var);
  private:
    int runOnSCC(const std::vector<CallGraphNode *> &SCC);
    int collectVarsOnFunction(Function *F, std::unordered_map<Value *, MDNode *>&Vals);
    bool hasLoop(Function *F, LoopInfo &LI);
    std::set<MDNode *> collectVarsOnLoop(Function *F, std::unordered_map<Value *, MDNode *> &Vals);
    std::set<MDNode *> collectVarsOnCond(Function *F, std::unordered_map<Value *, MDNode *>&Vals);
    std::set<MDNode *> collectVarsOnArgs(Function *F, std::unordered_map<Value *, MDNode *> &Vals);
    bool getOperand(Value *V, std::set<Value *> &operands, int depth);
    std::set<MDNode *> collectVarsFromVal(Value *V, Function *F, std::unordered_map<Value *, MDNode *> &Vals);
    MDNode* findLocalVar(Value* V, Function* F);
    int saveLocal(Function *F, std::set<MDNode *> &loopVars, std::set<MDNode *> &condVar, std::set<MDNode *> &argsVar);
    int saveGlobal(const Module&);
    bool loopNeedCheck(Loop *L);
    bool brNeedCheck(const BranchInst *BI);
    void set_volatile_flag(Instruction *I, Function *F);
    bool printMD(MDNode *var, std::string flag);
  };
}
#endif

#include "ProfileVar.hpp"
#include "llvm/IR/CFG.h"

static std::string getSimplebbLabel(const BasicBlock *bb) {
  const Function *F = bb->getParent();
  if (!bb->getName().empty())
    return F->getName().str() + '#' + bb->getName().str();

  std::string Str;
  raw_string_ostream OS(Str);

  bb->printAsOperand(OS, false);
  return F->getName().str() + '#' + OS.str();
}

static std::vector<std::string> record_precessors_successors(const BasicBlock *bb) {
  std::vector<std::string> sequences;
  for (const BasicBlock *Pred : predecessors(bb)) {
    sequences.push_back(getSimplebbLabel(Pred));
  }
  sequences.push_back(getSimplebbLabel(bb));
  for (const BasicBlock *Succ : successors(bb)) {
    sequences.push_back(getSimplebbLabel(Succ));
  }
  return sequences;
}

static void block2SrcRange(const BasicBlock *bb, int *begin, int *end) {
  for (auto it = bb->begin(), ed = bb->end(); it != ed; ++it) {
    const Instruction *I = &*it;
    if (isa<DbgInfoIntrinsic>(I))
        continue;
    const DebugLoc &Loc = I->getDebugLoc();
    if (!Loc)
      continue;
    if (Loc.getLine() == 0)
      continue;
    const int lineno = Loc.getLine();
    if (*begin == -1)
      *begin = lineno;
    else if (*begin > lineno)
      *begin = lineno;

    if (*end < lineno)
      *end = lineno;
  }
}

std::unordered_map<const Function *, std::vector<int>> visitedFunctions;

void SaveFunctionInfo(const Function *f) {
  if (visitedFunctions.find(f) == visitedFunctions.end())
    return;
  LogSrc2bb("function=%s,begin=%d,end=%d,filename=%s\n", 
      demangle(f->getName().str()).c_str(),
      visitedFunctions[f][0],
      visitedFunctions[f][1],
      f->getParent()->getSourceFileName().c_str());
}

void updateFunctionInfo(const Function *f, const int begin, const int end) {
  std::vector<int> location{begin, end};
  if (visitedFunctions.find(f) == visitedFunctions.end())
    visitedFunctions[f] = location;
  else {
    if (visitedFunctions[f][0] == -1 || begin < visitedFunctions[f][0])
      visitedFunctions[f][0] = begin;
    if (end > visitedFunctions[f][1])
      visitedFunctions[f][1] = end;
  }
}

void SaveBlockInfo(const BasicBlock *bb) {
  int beginLine = -1, endLine = -1;
  block2SrcRange(bb, &beginLine, &endLine);
  std::vector<std::string> seq = record_precessors_successors(bb);
  LogSrc2bb("tag=%s,begin=%d,end=%d;",
      getSimplebbLabel(bb).c_str(),
      beginLine,
      endLine);
  for (auto elem: seq)
    LogSrc2bb("%s,", elem.c_str());
  LogSrc2bb("\n");

  if (beginLine != -1 || endLine != -1)
    updateFunctionInfo(bb->getParent(), beginLine, endLine);
}

#include "ProfileVar.hpp"

std::string instDesc(Instruction *I) {
  std::string str;
  llvm::raw_string_ostream(str) << *I;
  return str;
}

std::string valDesc(Value *v) {
  std::string str;
  llvm::raw_string_ostream(str) << *v;
  return str;
}

void Log(const char *path, const char *fmt, ...)
{
  va_list mark;
  char buf[4096] = {0};
  va_start(mark, fmt);
  vsprintf(buf, fmt, mark);
  va_end(mark);
  std::string msg(buf);
  std::ofstream ofstr(path, std::ofstream::out|std::ofstream::app);
  if (!ofstr) 
    return;
  std::copy(msg.begin(), msg.end(), std::ostream_iterator<char>(ofstr));
}

std::unordered_map<Value*, Function* > cached_results;
std::unordered_map<Value*, std::vector<ValueEdge> > dst_edges; 

Function *search(std::unordered_map<Value *, std::vector<ValueEdge> > &dst_edges, Value *dst, std::set<Value *> &visited) {
  if (visited.count(dst) || dst_edges.find(dst) == dst_edges.end())
    return  NULL;
  if (cached_results.find(dst) != cached_results.end())
    return cached_results[dst];

  visited.insert(dst);
  std::vector<ValueEdge> &edges = dst_edges[dst];
  for (auto edge : edges) {
    if (edge.F) {
      cached_results[dst] = edge.F;
      return edge.F;
    }
    Value *src = edge.src;
    assert(edge.dst == dst);
    Function *f = search(dst_edges, src, visited);
    if (f)
      return f;
  }
  cached_results[dst] = NULL;
  return NULL;
}

void valueFlowInFunction(Function *F, std::unordered_map<Value *, MDNode *>vals) {
  //begin construct graph for the values in F
  cached_results.clear();
  dst_edges.clear();

  for (Function::iterator bb = F->begin(); bb != F->end(); ++bb) {
    BasicBlock *Block = &*bb;
    for (BasicBlock::iterator Iter = Block->begin(); Iter != Block->end(); ++Iter) {
      Instruction* Inst = &*Iter;
      if (dyn_cast<DbgDeclareInst>(Inst) || dyn_cast<DbgValueInst>(Inst))
        continue;

      Value *dst = NULL;
      Function *callee = NULL;
      switch(Inst->getOpcode()) {
        case Instruction::Store: {
                                   StoreInst *i = dyn_cast<StoreInst>(Inst);
                                   dst = i->getPointerOperand();
                                   if (dst_edges.find(dst) == dst_edges.end()) {
                                     std::vector<ValueEdge> empty;
                                     dst_edges[dst] = empty;
                                   }
                                   dst_edges[dst].push_back(ValueEdge(dst, i->getValueOperand(), callee));
                                   break;
                                 }
        case Instruction::Call: {
                                  CallInst *call = dyn_cast<CallInst>(Inst);
                                  callee = call->getCalledFunction();
                                  /*set the callee and fall throught to default*/
                                }
        default: {
                   dst = dyn_cast<Value>(Inst);
                   if (dst_edges.find(dst) == dst_edges.end()) {
                     std::vector<ValueEdge> empty;
                     dst_edges[dst] = empty;
                   }
                   for (int i = 0; i < Inst->getNumOperands(); ++i) {
                     dst_edges[dst].push_back(ValueEdge(dst, Inst->getOperand(i), callee));
                   }
                 }
      } //switch instruction

      if (vals.find(dst) != vals.end()) {
        //if the destination is a recored variable
        //search the related calculation function from the dst_edegs
        std::set<Value *> visited;
        visited.clear();
        Function *srcF = search(dst_edges, dst, visited);
        if (srcF) {
          const llvm::DebugLoc &debugInfo = Inst->getDebugLoc();
          if (!debugInfo) {
            continue;
          }
          std::string directory = debugInfo->getDirectory().str();
          std::string filePath = debugInfo->getFilename().str();
          int line = debugInfo->getLine();
          //int column = debugInfo->getColumn();
          DIVariable *node = dyn_cast<DIVariable>(vals[dst]);

          LogSchema("#ValueFlow:dir=%s,path=%s,func=%s,line=%d,var=%s,srcF=%s\n",
              directory.c_str(),
              filePath.c_str(),
              demangle(F->getName().str()).c_str(),
              line,
              node->getName().str().c_str(),
              demangle(srcF->getName().str()).c_str());
        }
      } //end of value search
    }//instruction
  }//block
}


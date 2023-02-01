#include "ProfileVar.hpp"
using namespace llvm;
namespace {
    std::string ProfileVarPass::getEnv(const char *var)
    {
      char *val = std::getenv(var);
      if (val == nullptr)
        return "Undefined";
      return val;
    }

    void ProfileVarPass::getAnalysisUsage(AnalysisUsage &AU) const 
    {
      AU.addRequired<ScalarEvolutionWrapperPass>();
			AU.addRequired<LoopInfoWrapperPass>();
      AU.addRequired<CallGraphWrapperPass>();
      AU.setPreservesAll();
    }
    
    bool ProfileVarPass::runOnModule(Module& m) 
    {
      CallGraph& cg = getAnalysis<CallGraphWrapperPass>().getCallGraph();
      const std::string &schema_comp = getEnv("SchemaComponent");
      if (schema_comp != "Undefined" && m.getName().str().find(schema_comp.c_str()) == std::string::npos)
        return false;
      
      int total_lines = 0;
      for (scc_iterator<CallGraph*> Iter = scc_begin(&cg); Iter != scc_end(&cg); ++Iter) {
        int lines = runOnSCC(*Iter);
        total_lines += lines;
      }
      saveGlobal(m);
      return false;
    }

    int ProfileVarPass::runOnSCC(const std::vector<CallGraphNode *> &SCC)
    {
      //Run pass on all functions current SCC
      int n = 0;
      for(auto i = SCC.begin(); i != SCC.end(); ++i) {
					CallGraphNode * const cgNode = *i;
          if (cgNode) {
            Function *F = cgNode->getFunction();
            if (!F || F->isDeclaration() || FuncMap.count(F))
              continue;
            FuncMap[F] = ~0;
            std::unordered_map<Value *, MDNode *> vals;
            vals.clear();
            n += collectVarsOnFunction(F, vals);
            valueFlowInFunction(F, vals);
          }
      }
      return n;
    }

    int ProfileVarPass::collectVarsOnFunction(Function *F, std::unordered_map<Value *, MDNode *> &Vals) {
      std::set<MDNode *> loopVars;
      std::set<MDNode *> condVars;
      std::set<MDNode *> argsVars;

      LoopInfo &LI = getAnalysis<LoopInfoWrapperPass>(*F).getLoopInfo();
      if (hasLoop(F, LI) == true)
        loopVars = collectVarsOnLoop(F, Vals);
      condVars = collectVarsOnCond(F, Vals);
      argsVars = collectVarsOnArgs(F, Vals);

      //Save schema for localvariable in function F
      return saveLocal(F, loopVars, condVars, argsVars);
    }

    bool ProfileVarPass::hasLoop(Function *F, LoopInfo &LI) {
      for (Function::iterator bb = F->begin(); bb != F->end(); ++bb) {
        BasicBlock *Block = &*bb;
        if (!Block || !LI.getLoopFor(Block))
          continue;
        else
          return true;
      }
      return false;
    }

    std::set<MDNode *> ProfileVarPass::collectVarsOnLoop(Function *F, std::unordered_map<Value *, MDNode *> &Vals) {
      std::set<MDNode *> loopVars;
      loopVars.clear();

      LoopInfo &LI = getAnalysis<LoopInfoWrapperPass>(*F).getLoopInfo();
      if (hasLoop(F, LI) == false)
        return loopVars;

      ScalarEvolution &SE = getAnalysis<ScalarEvolutionWrapperPass>(*F).getSE();
      for (Function::iterator bb = F->begin(); bb != F->end(); ++bb) {
        BasicBlock *Block = &*bb;
        if (!Block || !LI.getLoopFor(Block))
          continue;
        Loop *L = LI.getLoopFor(Block);
        //InductionVariable (cited from llvm developer's comment)
        /*To only detect and analyze induction variables, using ScalarEvolution
          is sufficient (you don't need SCEVExpander).  You have to get hold of
          a ScalarEvolution object (see the implementation of
          IndVarSimplifyLegacyPass or IndVarSimplifyPass on how to do that) and
          use the ScalarEvolution::getSCEV method to translate an llvm::Value*
          to an llvm::SCEV*.  If the llvm::SCEV* you get back is an
          llvm::SCEVAddRecExpr* (you can check this by dyn_cast<> or isa<>) then
          the llvm::Value* is an induction variable.*/
        bool found = false;         
        for (auto lb = L->block_begin(); lb != L->block_end(); lb++) {
          BasicBlock *Block = *lb;
          for (BasicBlock::iterator Iter = Block->begin(); Iter != Block->end(); ++Iter) {
            Instruction* I = &*Iter;
            for (User::op_iterator O = I->op_begin(); O != I->op_end(); ++O) {
              Value *o = dyn_cast<Value>(&*O);
              if (!o || !SE.isSCEVable(o->getType()))
                continue;
              const SCEV *scval = SE.getSCEV(o);
              if (scval && isa<SCEVAddRecExpr>(scval)) {
                std::set<MDNode *> ret = collectVarsFromVal(o, F, Vals);
                if (ret.size() > 0) {
                  loopVars.insert(ret.begin(), ret.end());
                  found = true;
                  break;
                }
              }
            }//loop operands
            if (found == true)
              break;
          }//loop instructions
          if (found == true)
            break;
        } //Find induction variable for loop_block in loop

      }//loop every block in function 
      return loopVars;
    }

    std::set<MDNode *> ProfileVarPass::collectVarsOnCond(Function *F, std::unordered_map<Value *, MDNode *> &Vals) {
      std::set<MDNode *> condVars;
      for (Function::iterator bb = F->begin(); bb != F->end(); ++bb) {
        BasicBlock *Block = &*bb;
        if (!Block)
          continue;
        //record basic block id mapping to src line
        SaveBlockInfo(Block);
        for (BasicBlock::iterator Iter = Block->begin(); Iter != Block->end(); ++Iter) {
          Instruction* I = &*Iter;
          if (!I)
            continue;
          //Branch instruction
          if (BranchInst *BI = dyn_cast<BranchInst>(I)) {
            if (BI->isConditional() && brNeedCheck(BI)) {
              Value* cond = BI->getCondition();
              if (cond && isa<CmpInst>(cond)) {
                std::set<MDNode *> ret = collectVarsFromVal(cond, F, Vals);
                if (ret.size() > 0)
                  condVars.insert(ret.begin(), ret.end());
              }
            } else {
              std::set<MDNode *> ret = collectVarsFromVal(dyn_cast<Value>(BI), F, Vals);
              if (ret.size() > 0)
                condVars.insert(ret.begin(), ret.end());
            }
          }
        }//loop over instruction
      }//loop over basicblocks
      SaveFunctionInfo(F);
      return condVars;
    }

    std::set<MDNode *> ProfileVarPass::collectVarsOnArgs(Function *F, std::unordered_map<Value *, MDNode *>&Vals) {
      std::set<MDNode *> argsVars;
      for (Function::iterator bb = F->begin(); bb != F->end(); ++bb) {
        BasicBlock *Block = &*bb;
        if (!Block)
          continue;
        for (BasicBlock::iterator Iter = Block->begin(); Iter != Block->end(); ++Iter) {
          Instruction* I = &*Iter;
          if (!I)
            continue;
          //Callees
          if (CallBase* Call = dyn_cast<CallBase>(I)) {
            for (User::op_iterator cbIter = Call->arg_begin(); cbIter != Call->arg_end(); ++cbIter) {
                std::set<MDNode *> ret = collectVarsFromVal(dyn_cast<Value>(&*cbIter), F, Vals);
                argsVars.insert(ret.begin(), ret.end());
            }
          }
        } //instructions
      } //blocks
      return argsVars;
    }


    const int max_depth = 8;
    //prevent stack overflow on instructions like phi
    bool ProfileVarPass::getOperand(Value *V, std::set<Value *> &operands, int depth) {
      if (!V || depth >= max_depth)
        return false;
      depth++;
      if (Instruction *I = dyn_cast<Instruction>(V)) {
        unsigned n = I->getNumOperands();
        for (unsigned i = 0; i < n; i++) {
          getOperand(I->getOperand(i), operands, depth);
        }
      }
      if (GEPOperator *I = dyn_cast<GEPOperator>(V)) {
        for (auto Iter = I->idx_begin(), E = I->idx_end(); Iter != E; ++Iter) {
          if (!dyn_cast<ConstantInt>(&*Iter)) {
            if (Value * op = dyn_cast<Value>(&*Iter))
              operands.insert(op);
          }
        }
      }
      operands.insert(V);
      return false;
    }

    std::set<MDNode *> ProfileVarPass::collectVarsFromVal(Value *V, Function *F, std::unordered_map<Value *, MDNode *> &Vals) {
      std::set<MDNode *> ret;
      if (!V) 
        return ret;
      std::set<Value *> operands;
      getOperand(V, operands, 0);

      for (auto v: operands) {
        //local variable 
        if (MDNode *node = findLocalVar(v, F))
            ret.insert(node);
        if (Instruction *I = dyn_cast<Instruction>(v)) {
            if (MDNode *node = findLocalVar(I->getOperand(0), F)) {
              ret.insert(node);
              Vals[I->getOperand(0)] = node;
            }
        }
        //global variable 
        if (GlobalValue* G = dyn_cast<GlobalValue>(&*v)) {
            Globals.insert(G);
        }
      }
      return ret;
    }

    /*find local variables*/
    MDNode* ProfileVarPass::findLocalVar(Value* V, Function* F) {
      if (!V)
        return NULL;
      for (Function::iterator bb = F->begin(); bb != F->end(); ++bb) {
        BasicBlock *Block = &*bb;
        if (!Block)
          continue;
        for (BasicBlock::iterator Iter = Block->begin(); Iter != Block->end(); ++Iter) {
          Instruction* I = &*Iter;
          if (const DbgDeclareInst* DbgDeclare = dyn_cast<DbgDeclareInst>(I)) {
            if (DbgDeclare->getAddress() == V) 
              return DbgDeclare->getVariable();
          } else if (const DbgValueInst* DbgValue = dyn_cast<DbgValueInst>(I)) {
            if (DbgValue->getValue() == V) 
              return DbgValue->getVariable();
          }
        }
      }
      return NULL;
    }

    int ProfileVarPass::saveLocal(Function *F, std::set<MDNode *> &loopVars, std::set<MDNode *> &condVar, std::set<MDNode *> &argsVar) {
      std::map<MDNode *, std::string> result;
      for (auto node : loopVars) {
        assert(node != NULL);
        if (result.find(node) == result.end()) {
          std::string flag("loop");
          result[node] = flag;
        }
      }
      std::string condflag("cond");
      for (auto node : condVar) {
        assert(node != NULL);
        if (result.find(node) == result.end()) {
          result[node] = condflag;
        } else {
          if (result[node].find("cond") == std::string::npos)
            result[node] = result[node] + "|cond";
        }
      }
      std::string argflag("args");
      for (auto node : argsVar) {
        assert(node != NULL);
        if (result.find(node) == result.end()) {
          result[node] = argflag;
        } else {
          if (result[node].find("args") == std::string::npos)
            result[node] = result[node] + "|args";
        }
      }

      for (auto const& var : result) {
        DIVariable *node = dyn_cast<DIVariable>(var.first);
        if (!node)
          continue;
        //set the default type, in case Type name is not available
        std::string type("uintptr");
        if (node->getType()) {
          type = node->getType()->getName().str();
          std::replace(type.begin(), type.end(), ' ', '#');
        }
				LogSchema("%s %s %s %d %s %s %s\n", node->getDirectory().str().c_str(),
						node->getFilename().str().c_str(),
						demangle(F->getName().str()).c_str(),
						node->getLine(),
						node->getName().str().c_str(),
						type.size() == 0 ? "uintptr" : type.c_str(),
						var.second.c_str());
      }
      return result.size();
    }

    int ProfileVarPass::saveGlobal(const Module& m)
    {
      NamedMDNode *CUNodes = m.getNamedMetadata("llvm.dbg.cu");
      if (!CUNodes)
        return -1;
      for (unsigned I = 0, E = CUNodes->getNumOperands(); I != E; ++I) {
        auto *CU = cast<DICompileUnit>(CUNodes->getOperand(I));
        auto *GVs = dyn_cast_or_null<MDTuple>(CU->getRawGlobalVariables());
        if (!GVs)
          continue;
        for (unsigned I = 0; I < GVs->getNumOperands(); I++) {
          auto *GV = dyn_cast_or_null<DIGlobalVariableExpression>(GVs->getOperand(I));
          if (!GV)
            continue;
          DIGlobalVariable *Var = GV->getVariable();
          for (auto gVal: Globals) {
            if (gVal->getGlobalIdentifier() != Var->getName())
              continue;
            //set the default type, in case Type name is not available
            std::string type("uintptr");
            if (Var->getType()) {
              type = Var->getType()->getName().str();
              std::replace(type.begin(), type.end(), ' ', '#');
            } 
            LogSchema("%s %s %s %d %s %s %s\n",
                Var->getDirectory().str().c_str(),
                Var->getFilename().str().c_str(),
                "#global",
                Var->getLine(),
                Var->getName().str().c_str(),
                type.size() == 0 ? "uintptr" : type.c_str(), "globalVar");
            Globals.erase(gVal);
            break;
          }
        }
      }
      return Globals.size();
    }
    
    //loop filter
    bool ProfileVarPass::loopNeedCheck(Loop *L) {
      return true;
    }

    //control flow filters
    bool ProfileVarPass::brNeedCheck(const BranchInst *BI) {
      unsigned int n = BI->getNumSuccessors();
      if (n < 2)
        return false;
      unsigned int i;
      for (i = 0; i < n; i++) {
          BasicBlock* Block = BI->getSuccessor(i);
          if (Block == NULL)
            continue;
          for (BasicBlock::iterator Iter = Block->begin(); Iter != Block->end(); ++Iter) {
            const Instruction* I = &*Iter;
            if (isa<BranchInst>(I) || isa<CallInst>(I) || isa<InvokeInst>(I))
              return true;
          }
      }
      return false;
    }

#ifdef DEBUG_MDNode
    bool ProfileVarPass::printMD(MDNode *var, std::string flag) {
      DIVariable *node = dyn_cast<DIVariable>(var);
      if (!node)
        return false;
      errs() << node->getDirectory() << " ";
      errs() << node->getFilename() << " ";
      errs() << node->getLine() << " ";
      errs() << node->getName() << " ";
      std::string type("uintptr");
      if (node->getType()) {
          type = node->getType()->getName().str();
          std::replace(type.begin(), type.end(), ' ', '#');
      } 
      errs() << type << " " << flag << "\n";
      return true;
    }
#endif
} //namespace

//==========Do not touch the code below=============
char ProfileVarPass::ID = 0;
// Automatically enable the pass.
static void registerProfileVarPass(const PassManagerBuilder &,
                         legacy::PassManagerBase &PM) {
  PM.add(new llvm::CallGraphWrapperPass);
  PM.add(new llvm::LoopInfoWrapperPass);
  PM.add(new llvm::ScalarEvolutionWrapperPass);
  PM.add(new ProfileVarPass());
}

static RegisterStandardPasses
  RegisterMyPass(PassManagerBuilder::EP_ModuleOptimizerEarly, registerProfileVarPass);
static RegisterStandardPasses
  RegisterMyPass0(PassManagerBuilder::EP_EnabledOnOptLevel0, registerProfileVarPass);

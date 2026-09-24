"""Diagnostic-only import hook; preserves scheduler decisions and cache calls."""
import os
if os.environ.get('PD_QUERY_DIAGNOSTIC_DIR'):
 import importlib.abc,importlib.machinery,sys
 from query_probe import instrument
 class Loader(importlib.abc.Loader):
  def __init__(self,original):self.original=original
  def create_module(self,spec):return self.original.create_module(spec) if hasattr(self.original,'create_module') else None
  def exec_module(self,module):
   self.original.exec_module(module);instrument(module)
 class Finder(importlib.abc.MetaPathFinder):
  def find_spec(self,fullname,path=None,target=None):
   if fullname not in ('vllm.v1.core.single_type_kv_cache_manager','vllm.v1.core.kv_cache_manager','vllm.v1.core.sched.scheduler'):return None
   spec=importlib.machinery.PathFinder.find_spec(fullname,path)
   if spec and spec.loader:spec.loader=Loader(spec.loader)
   return spec
 sys.meta_path.insert(0,Finder())

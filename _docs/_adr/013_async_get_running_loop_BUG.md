# Trigger
Some times there were threads concurrency problems due to get_running_loop

# Details
cf core/thread.py for implementation

commit 22f7201fe25be02b4d6846d1d34c10a8ba348f2c
Author: johannoriel <johannoriel6@gmail.com>
:
index 61a41c1..a0829a6 100644
--- a/modules/trainer/plugins/pedagogical_memory/core.py
+++ b/modules/trainer/plugins/pedagogical_memory/core.py
@@ -66,22 +66,6 @@ class PedagogicalAnalysisLog(Base):
     facts_discarded = Column(Integer, default=0)
     created_at = Column(DateTime, default=datetime.utcnow)
 
-
-def _run_async(coro):
-    try:
-        loop = asyncio.get_running_loop()
-    except RuntimeError:
-        loop = None
-
-    if loop and loop.is_running():
-        import concurrent.futures
-        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
-            future = pool.submit(asyncio.run, coro)
-            return future.result()
-    else:
-        return asyncio.run(coro)
-
-
 class PedagogicalMemoryPluginCore(TrainerPluginCore):
 
     def __init__(self, plugin_id: str = None):
@@ -713,7 +697,9 @@ class PedagogicalMemoryPluginCore(TrainerPluginCore):
     def _action_trigger_analysis(self, context, **params) -> Dict:
         from shared.common import record_plugin_event
 
-        result = _run_async(self.refresh_memory(context.trainer_id, context.student_id))
+        result = asyncio.run(
+            self.refresh_memory(context.trainer_id, context.student_id)
+        )
 
         event_data = {
             "success": True,

FROM =====================================================

import asyncio
from shared.common import get_llm_manager
manager = get_llm_manager()
messages = [{"role": "user", "content": prompt}]

async def _call():
    return await manager.internal_response(manager.current_llm, messages)

try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = None

if loop and loop.is_running():
    # Already inside an event loop (e.g. Streamlit) — run in a sibling thread.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _call()).result(timeout=30)
else:
    return asyncio.run(_call())

TO ========================================================
import asyncio
import concurrent.futures
manager = self._get_llm_manager()
messages = [{"role": "user", "content": prompt}]

def _run_in_thread():
    return asyncio.run(
        manager.internal_response(manager.current_llm, messages)
    )

with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
    return pool.submit(_run_in_thread).result(timeout=30)

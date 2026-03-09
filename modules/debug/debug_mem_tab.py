"""
Debug Memory Tab
===============

Provides memory profiling tools to identify memory usage and potential leaks.
Shows memory usage by object types, session state, and cached resources.
"""

import streamlit as st
import sys
import os
import gc
import inspect
from typing import Dict, Any, List, Optional
import psutil
import objgraph

# Try to import memory profiler tools
try:
    from pympler import tracker, muppy, summary, asizeof
    PYMPLER_AVAILABLE = True
except ImportError:
    PYMPLER_AVAILABLE = False

try:
    import tracemalloc
    tracemalloc.start()
    TRACEMALLOC_AVAILABLE = True
except ImportError:
    TRACEMALLOC_AVAILABLE = False


def get_process_memory() -> Dict[str, float]:
    """Get current process memory usage in MB."""
    process = psutil.Process()
    mem_info = process.memory_info()

    # Get memory maps for shared libraries
    try:
        maps = process.memory_maps()
        shared_memory = sum(m.private_dirty + m.shared_dirty for m in maps) / 1024 / 1024
    except:
        shared_memory = 0

    return {
        "rss": mem_info.rss / 1024 / 1024,
        "vms": mem_info.vms / 1024 / 1024,
        "shared": shared_memory,
        "percent": process.memory_percent(),
    }


def get_object_size(obj: Any) -> float:
    """Get size of an object in MB with safe error handling."""
    if not PYMPLER_AVAILABLE:
        return 0

    try:
        # Try to get size safely
        return asizeof.asizeof(obj) / 1024 / 1024
    except (TypeError, ReferenceError, AttributeError, RuntimeError):
        # Object types that cause issues with weakref
        return 0
    except Exception:
        # Any other error, just return 0
        return 0


def safe_get_object_size(obj: Any) -> Dict:
    """Safely get object size with error handling."""
    try:
        size = get_object_size(obj)
        obj_type = type(obj).__name__
        return {
            "size_mb": size,
            "size_str": format_size(size),
            "type": obj_type,
            "error": None
        }
    except Exception as e:
        return {
            "size_mb": 0,
            "size_str": "0 B",
            "type": type(obj).__name__,
            "error": str(e)[:50]
        }


def format_size(size_mb: float) -> str:
    """Format memory size with appropriate unit."""
    if size_mb < 0.001:
        return f"{size_mb*1024*1024:.1f} B"
    if size_mb < 1:
        return f"{size_mb*1024:.1f} KB"
    if size_mb < 1024:
        return f"{size_mb:.1f} MB"
    return f"{size_mb/1024:.1f} GB"


def analyze_session_state() -> Dict[str, Any]:
    """Analyze memory usage of session state with safe error handling."""
    total_size = 0
    key_sizes = []
    error_count = 0

    for key, value in st.session_state.items():
        size_info = safe_get_object_size(value)
        total_size += size_info["size_mb"]

        if size_info["error"]:
            error_count += 1

        key_sizes.append({
            "key": key,
            "size_mb": size_info["size_mb"],
            "size_str": size_info["size_str"],
            "type": size_info["type"],
            "error": size_info["error"]
        })

    # Sort by size descending
    key_sizes.sort(key=lambda x: x["size_mb"], reverse=True)

    return {
        "total_mb": total_size,
        "total_str": format_size(total_size),
        "key_count": len(st.session_state),
        "error_count": error_count,
        "keys": key_sizes,
    }


def analyze_cache_objects():
    """Analyze st.cache_resource objects by inspecting internal Streamlit state."""
    cache_info = {
        "cache_resource": {},
        "cache_data": {},
        "total_entries": 0,
        "estimated_size_mb": 0,
        "cached_objects": []
    }

    # Inspect Streamlit's internal cache
    try:
        # Access Streamlit's internal cache registry
        if hasattr(st, '_main') and hasattr(st._main, '_cache'):
            # This is the internal cache dict
            cache_dict = st._main._cache

            # For cache_resource (st.cache_resource)
            if hasattr(cache_dict, '_resource_cache'):
                resource_cache = cache_dict._resource_cache
                if hasattr(resource_cache, '_caches'):
                    for cache_name, cache in resource_cache._caches.items():
                        if hasattr(cache, '_dict'):
                            entries = list(cache._dict.items())
                            cache_info["total_entries"] += len(entries)

                            for key, value in entries:
                                # Try to identify what's cached
                                obj_info = {
                                    "type": type(value).__name__,
                                    "key": str(key)[:100],
                                    "cache_type": "resource",
                                    "name": cache_name
                                }

                                # Try to get size
                                try:
                                    from pympler import asizeof
                                    size = asizeof.asizeof(value) / 1024 / 1024
                                    obj_info["size_mb"] = size
                                    cache_info["estimated_size_mb"] += size
                                except:
                                    obj_info["size_mb"] = 0

                                cache_info["cached_objects"].append(obj_info)

            # For cache_data (st.cache_data)
            if hasattr(cache_dict, '_data_cache'):
                data_cache = cache_dict._data_cache
                if hasattr(data_cache, '_caches'):
                    for cache_name, cache in data_cache._caches.items():
                        if hasattr(cache, '_dict'):
                            entries = list(cache._dict.items())
                            cache_info["total_entries"] += len(entries)

                            for key, value in entries:
                                obj_info = {
                                    "type": type(value).__name__,
                                    "key": str(key)[:100],
                                    "cache_type": "data",
                                    "name": cache_name
                                }

                                try:
                                    from pympler import asizeof
                                    size = asizeof.asizeof(value) / 1024 / 1024
                                    obj_info["size_mb"] = size
                                    cache_info["estimated_size_mb"] += size
                                except:
                                    obj_info["size_mb"] = 0

                                cache_info["cached_objects"].append(obj_info)
    except Exception as e:
        cache_info["error"] = str(e)

    # Try to get embedding model info (already working)
    try:
        from st_shared.cached import get_llm_manager
        llm = get_llm_manager()

        if hasattr(llm, "_embedding_model") and llm._embedding_model:
            from pympler import asizeof
            size = asizeof.asizeof(llm._embedding_model) / 1024 / 1024
            cache_info["embedding_model_mb"] = size

            # Add as cached object if not already there
            cache_info["cached_objects"].append({
                "type": "SentenceTransformer",
                "name": "embedding_model",
                "size_mb": size,
                "cache_type": "internal",
                "key": llm.embedding_model_name
            })

        if hasattr(llm, "_model_cache") and llm._model_cache:
            total_size = 0
            for model_name, model in llm._model_cache.items():
                try:
                    size = asizeof.asizeof(model) / 1024 / 1024
                    total_size += size
                    cache_info["cached_objects"].append({
                        "type": "SentenceTransformer",
                        "name": "model_cache",
                        "size_mb": size,
                        "cache_type": "internal",
                        "key": model_name
                    })
                except:
                    pass

            cache_info["model_cache_mb"] = total_size
    except:
        pass

    # Sort cached objects by size
    cache_info["cached_objects"].sort(key=lambda x: x.get("size_mb", 0), reverse=True)

    return cache_info


def get_largest_objects(limit: int = 20) -> List[Dict]:
    """Get largest objects in memory by type with safe handling."""
    if not PYMPLER_AVAILABLE:
        return []

    try:
        all_objects = muppy.get_objects()
        obj_summary = summary.summarize(all_objects)

        # Convert to list and sort by size
        objects = []
        for obj_type, count, total_size in obj_summary:
            objects.append({
                "type": obj_type,
                "count": count,
                "total_mb": total_size / 1024 / 1024,
                "total_str": format_size(total_size / 1024 / 1024),
                "avg_mb": (total_size / count) / 1024 / 1024 if count else 0,
            })

        objects.sort(key=lambda x: x["total_mb"], reverse=True)
        return objects[:limit]
    except Exception:
        return []


def get_tracemalloc_snapshot(top_n: int = 10):
    """Get tracemalloc snapshot showing biggest allocations."""
    if not TRACEMALLOC_AVAILABLE:
        return None

    try:
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics('lineno')

        result = []
        total_size = sum(stat.size for stat in top_stats) / 1024 / 1024

        for stat in top_stats[:top_n]:
            trace = stat.traceback[0] if stat.traceback else None
            result.append({
                "size_mb": stat.size / 1024 / 1024,
                "size_str": format_size(stat.size / 1024 / 1024),
                "count": stat.count,
                "file": trace.filename.split('/')[-1] if trace else "unknown",
                "line": trace.lineno if trace else 0,
            })

        return {
            "total_mb": total_size,
            "total_str": format_size(total_size),
            "top": result,
        }
    except Exception:
        return None


def get_gc_stats() -> Dict:
    """Get garbage collector statistics."""
    return {
        "garbage_count": len(gc.garbage),
        "thresholds": gc.get_threshold(),
        "counts": gc.get_count(),
    }


def show_memory_tab():
    """Main memory debug tab UI."""
    st.header("📊 Memory Usage Analysis")

    # System memory info
    col1, col2, col3, col4 = st.columns(4)

    try:
        mem = get_process_memory()
        system_mem = psutil.virtual_memory()

        with col1:
            st.metric("RSS Memory", f"{mem['rss']:.1f} MB",
                     delta=f"{mem['percent']:.1f}% of system")
        with col2:
            st.metric("VMS Memory", f"{mem['vms']:.1f} MB")
        with col3:
            st.metric("Shared Memory", f"{mem['shared']:.1f} MB")
        with col4:
            st.metric("System RAM", f"{system_mem.percent}% used",
                     delta=f"{system_mem.available/1024/1024/1024:.1f} GB free")
    except:
        st.error("Failed to get system memory info")

    st.divider()

    # Control buttons
    col_gc, col_obj, col_snap, col_clear = st.columns(4)

    with col_gc:
        if st.button("🧹 Run Garbage Collector", use_container_width=True):
            freed = gc.collect()
            st.success(f"Garbage collector ran. Freed {freed} objects.")
            st.rerun()

    with col_obj:
        if st.button("🔍 Analyze Objects", use_container_width=True):
            st.session_state.show_obj_analysis = True

    with col_snap:
        if st.button("📸 Take Memory Snapshot", use_container_width=True):
            st.session_state.take_snapshot = True

    with col_clear:
        if st.button("🗑️ Clear All Results", use_container_width=True):
            for key in ["show_obj_analysis", "take_snapshot"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

    st.divider()

    # Session State Analysis
    with st.expander("💾 Session State Memory", expanded=True):
        session_stats = analyze_session_state()

        col_ss1, col_ss2, col_ss3 = st.columns(3)
        with col_ss1:
            st.metric("Total Session State", session_stats["total_str"])
        with col_ss2:
            st.metric("Keys", session_stats["key_count"])
        with col_ss3:
            if session_stats["error_count"] > 0:
                st.warning(f"⚠️ {session_stats['error_count']} objects couldn't be measured")

        if session_stats["keys"]:
            # Show top 10 largest keys
            data = []
            for k in session_stats["keys"][:10]:
                row = {"key": k["key"], "size": k["size_str"], "type": k["type"]}
                if k.get("error"):
                    row["error"] = k["error"]
                data.append(row)

            st.dataframe(
                data,
                column_config={
                    "key": "Key",
                    "size": "Size",
                    "type": "Type",
                    "error": "Error",
                },
                hide_index=True,
                use_container_width=True
            )

            if len(session_stats["keys"]) > 10:
                st.caption(f"Showing top 10 of {len(session_stats['keys'])} keys")

    # Cache Analysis
    with st.expander("🔄 Cache Resources", expanded=True):
        cache_info = analyze_cache_objects()

        if cache_info.get("cached_objects"):
            # Summary metrics
            col_c1, col_c2, col_c3 = st.columns(3)
            with col_c1:
                st.metric("Total Cache Entries", cache_info.get("total_entries", 0))
            with col_c2:
                est_size = cache_info.get("estimated_size_mb", 0)
                st.metric("Estimated Size", f"{est_size:.1f} MB")
            with col_c3:
                model_count = sum(1 for obj in cache_info["cached_objects"]
                                if obj.get("type") == "SentenceTransformer")
                st.metric("ML Models", model_count)

            st.divider()

            # Display cached objects in a table
            st.subheader("📋 Cached Objects by Size")

            # Prepare data for display
            table_data = []
            for obj in cache_info["cached_objects"]:
                size = obj.get("size_mb", 0)
                table_data.append({
                    "Type": obj.get("type", "Unknown"),
                    "Key": obj.get("key", "")[:50],
                    "Cache": obj.get("cache_type", "unknown"),
                    "Size": f"{size:.1f} MB" if size > 0 else "Unknown",
                    "Size MB": size  # For sorting
                })

            # Sort by size
            table_data.sort(key=lambda x: x["Size MB"], reverse=True)

            # Display as dataframe
            st.dataframe(
                table_data,
                column_config={
                    "Type": "Object Type",
                    "Key": "Key/Name",
                    "Cache": "Cache Type",
                    "Size": "Memory"
                },
                hide_index=True,
                use_container_width=True
            )

            # Highlight large objects
            large_objects = [obj for obj in cache_info["cached_objects"]
                            if obj.get("size_mb", 0) > 100]
            if large_objects:
                st.warning(f"⚠️ {len(large_objects)} large objects (>100MB) detected")
                for obj in large_objects:
                    st.write(f"- {obj.get('type')}: {obj.get('size_mb', 0):.1f} MB")

            # Detailed view in expander
            with st.expander("🔧 Detailed Cache Info", expanded=False):
                # Show raw cache info without binary data
                safe_info = {}
                for k, v in cache_info.items():
                    if k != "cached_objects":  # We already displayed this
                        if not isinstance(v, (bytes, bytearray)):
                            safe_info[k] = v

                st.json(safe_info)

                # Option to clear cache
                if st.button("🗑️ Clear All Caches", use_container_width=True):
                    try:
                        if hasattr(st, '_main') and hasattr(st._main, '_cache'):
                            cache_dict = st._main._cache
                            if hasattr(cache_dict, '_resource_cache'):
                                cache_dict._resource_cache.clear()
                            if hasattr(cache_dict, '_data_cache'):
                                cache_dict._data_cache.clear()
                        st.success("Caches cleared!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to clear caches: {e}")
        else:
            st.warning("""
            **Could not inspect Streamlit cache directly**

            To see cached objects, try:
            1. Install pympler: `pip install pympler`
            2. Use this code to manually inspect your cached functions:
            """)

            # Show what we do know
            if cache_info.get("embedding_model_mb"):
                st.info(f"✅ **Embedding Model**: {cache_info['embedding_model_mb']:.1f} MB")

            if cache_info.get("model_cache_mb"):
                st.info(f"✅ **Model Cache**: {cache_info['model_cache_mb']:.1f} MB")

    # Object Type Analysis
    if st.session_state.get("show_obj_analysis", False):
        with st.expander("📦 Largest Object Types", expanded=True):
            if PYMPLER_AVAILABLE:
                objects = get_largest_objects(30)

                if objects:
                    st.dataframe(
                        objects,
                        column_config={
                            "type": "Object Type",
                            "count": "Count",
                            "total_str": "Total Size",
                            "avg_mb": st.column_config.NumberColumn("Avg Size (MB)", format="%.3f"),
                        },
                        hide_index=True,
                        use_container_width=True
                    )

                    # Show raw object analysis option
                    if st.button("Show Full Object Analysis (may be slow)"):
                        try:
                            all_objects = muppy.get_objects()
                            st.write(f"Total objects: {len(all_objects)}")
                            st.write(summary.summarize(all_objects))
                        except Exception as e:
                            st.error(f"Failed: {e}")
                else:
                    st.warning("No object data available")
            else:
                st.warning("Install pympler for detailed object analysis: pip install pympler")

    # Tracemalloc Snapshot
    if st.session_state.get("take_snapshot", False):
        with st.expander("📊 Memory Allocation Snapshot", expanded=True):
            if TRACEMALLOC_AVAILABLE:
                snapshot = get_tracemalloc_snapshot(20)

                if snapshot and snapshot["top"]:
                    st.metric("Total allocated", snapshot["total_str"])

                    st.dataframe(
                        snapshot["top"],
                        column_config={
                            "size_str": "Size",
                            "count": "Blocks",
                            "file": "File",
                            "line": "Line",
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                else:
                    st.info("Take another snapshot to see changes")
            else:
                st.warning("tracemalloc is available but no snapshot taken")

    # GC Stats
    with st.expander("🗑️ Garbage Collector", expanded=False):
        gc_stats = get_gc_stats()

        col_gc1, col_gc2, col_gc3 = st.columns(3)
        with col_gc1:
            st.metric("Garbage Objects", gc_stats["garbage_count"])
        with col_gc2:
            st.metric("GC Thresholds", f"{gc_stats['thresholds']}")
        with col_gc3:
            st.metric("GC Counts", f"{gc_stats['counts']}")

        if gc_stats["garbage_count"] > 0:
            st.warning(f"⚠️ {gc_stats['garbage_count']} uncollectable objects detected")

    # Memory Leak Detection Tips
    with st.expander("🔍 Memory Leak Detection Tips", expanded=False):
        st.markdown("""
        **Common memory leak sources:**
        - **Cached models** (SentenceTransformer, LLMs) staying in memory
        - **Session state** accumulating large objects
        - **Callback registrations** not being cleaned up
        - **Global variables** holding references
        - **Thread locals** not being cleared

        **Check these:**
        1. Monitor if memory grows over time without returning to baseline
        2. Compare before/after snapshots of operations
        3. Look for objects that should have been garbage collected
        4. Check for circular references in data structures
        """)


def inject_ui_debug_memory():
    """Injection point for the memory debug tab."""
    return show_memory_tab

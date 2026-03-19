"""
Handler Registry — maps handler keys to handler functions.
Single source of truth for CUSTOM_HANDLERS and TOOL_DEFS.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# ── rg_tool_registry volume mount ──
try:
    from rg_tool_registry import ToolRegistry
    from rg_tool_registry.builtin_tools import build_registry, ALL_TOOLS
    from rg_tool_registry.observability import ToolObserver as _ToolObserver
    _registry = build_registry()
    _agentic_observer = _ToolObserver(system="agentic_chat")
    _HAS_REGISTRY = True
except ImportError:
    _registry = None
    _agentic_observer = None
    _HAS_REGISTRY = False
    logger.warning("[REGISTRY] rg_tool_registry not found — tool definitions will be limited")

# ── Import all handler functions ──
from .handlers import (
    _custom_cv_scan, _custom_cv_trace, _custom_cv_functions, _custom_cv_governance,
    _custom_cv_list, _custom_cv_full_analysis, _custom_cv_report, _custom_cv_graph,
    _custom_cv_pipeline, _custom_cv_filter, _custom_cv_by_type, _custom_cv_compare,
    _custom_cv_delete,
    _custom_memory_search, _custom_memory_stats,
    _custom_hs_search, _custom_hs_anchor, _custom_hs_list_anchors, _custom_hs_hash, _custom_hs_resonance,
    _local_file_read, _local_file_write, _local_file_edit, _local_file_list, _local_file_delete,
)
from .handlers_agents import (
    _custom_agents_list, _custom_agents_create, _custom_agents_start, _custom_agents_stop,
    _custom_agents_delete, _custom_agents_status, _custom_agents_sessions,
    _custom_agents_session_steps, _custom_agents_session_trace, _custom_agents_metrics,
    _custom_agents_session_detail, _custom_agents_session_cancel, _custom_agents_update,
    _custom_agents_available_tools, _custom_agents_templates, _custom_agents_versions,
    _custom_agent_snapshot, _custom_run_agent,
)
from .handlers_state_physics import (
    _custom_sp_state, _custom_sp_reset, _custom_sp_nodes, _custom_sp_metrics,
    _custom_sp_identity, _custom_sp_simulate, _custom_sp_galaxy, _custom_sp_demo,
    _custom_sp_asymmetry, _custom_sp_physics_config, _custom_sp_entropy_config,
    _custom_sp_entropy_toggle, _custom_sp_entropy_perturbation, _custom_sp_agent_spawn,
    _custom_sp_agent_step, _custom_sp_agent_kill, _custom_sp_agents_spawn,
    _custom_sp_agents_kill_all, _custom_sp_experiment, _custom_sp_memory_cost,
    _custom_sp_metrics_record,
)
from .handlers_web import (
    _custom_web_search, _custom_read_webpage, _custom_read_many_pages,
    _custom_reddit_search, _custom_news_search,
)
from .handlers_github import (
    _custom_github_create_repo, _custom_github_list_repos, _custom_github_list_files,
    _custom_github_download_file, _custom_github_upload_file, _custom_github_commits,
    _custom_github_pull_request, _custom_github_issue, _custom_github_comment,
    _custom_git_proxy,
)
from .handlers_rabbit import (
    _custom_rabbit_create_community, _custom_rabbit_list_communities,
    _custom_rabbit_get_community, _custom_rabbit_create_post, _custom_rabbit_list_posts,
    _custom_rabbit_search_posts, _custom_rabbit_get_post, _custom_rabbit_delete_post,
    _custom_rabbit_create_comment, _custom_rabbit_list_comments, _custom_rabbit_delete_comment,
    _custom_rabbit_vote,
)
from .handlers_utilities import (
    _custom_get_current_time, _custom_get_system_info, _custom_weather,
    _custom_image_search, _custom_places_search, _custom_youtube_search,
    _custom_stock_crypto, _custom_deep_research, _custom_generate_chart,
    _custom_send_email, _custom_wikipedia, _custom_visualize,
)
from .handlers_orchestrator import (
    _custom_present_options, _custom_workspace_snapshot, _custom_schedule_agent,
    _custom_run_snapshot, _custom_session_log, _custom_create_tool, _custom_list_tools,
    _custom_delete_tool, _custom_update_tool,
)

CUSTOM_HANDLERS = {
    # Memory & Hash Sphere
    "_custom_memory_search": _custom_memory_search,
    "_custom_memory_stats": _custom_memory_stats,
    "_custom_hs_search": _custom_hs_search,
    "_custom_hs_anchor": _custom_hs_anchor,
    "_custom_hs_list_anchors": _custom_hs_list_anchors,
    "_custom_hs_hash": _custom_hs_hash,
    "_custom_hs_resonance": _custom_hs_resonance,
    # Code Visualizer
    "_custom_cv_scan": _custom_cv_scan,
    "_custom_cv_full_analysis": _custom_cv_full_analysis,
    "_custom_cv_trace": _custom_cv_trace,
    "_custom_cv_functions": _custom_cv_functions,
    "_custom_cv_governance": _custom_cv_governance,
    "_custom_cv_list": _custom_cv_list,
    "_custom_cv_report": _custom_cv_report,
    "_custom_cv_graph": _custom_cv_graph,
    "_custom_cv_pipeline": _custom_cv_pipeline,
    "_custom_cv_filter": _custom_cv_filter,
    "_custom_cv_by_type": _custom_cv_by_type,
    "_custom_cv_compare": _custom_cv_compare,
    "_custom_cv_delete": _custom_cv_delete,
    # Local IDE file tools
    "_local_file_read": _local_file_read,
    "_local_file_write": _local_file_write,
    "_local_file_edit": _local_file_edit,
    "_local_file_list": _local_file_list,
    "_local_file_delete": _local_file_delete,
    # Agents
    "_custom_agents_list": _custom_agents_list,
    "_custom_agents_create": _custom_agents_create,
    "_custom_agents_start": _custom_agents_start,
    "_custom_agents_stop": _custom_agents_stop,
    "_custom_agents_delete": _custom_agents_delete,
    "_custom_agents_status": _custom_agents_status,
    "_custom_agents_sessions": _custom_agents_sessions,
    "_custom_agents_session_steps": _custom_agents_session_steps,
    "_custom_agents_session_trace": _custom_agents_session_trace,
    "_custom_agents_metrics": _custom_agents_metrics,
    "_custom_agents_session_detail": _custom_agents_session_detail,
    "_custom_agents_session_cancel": _custom_agents_session_cancel,
    "_custom_agents_update": _custom_agents_update,
    "_custom_agents_available_tools": _custom_agents_available_tools,
    "_custom_agents_templates": _custom_agents_templates,
    "_custom_agents_versions": _custom_agents_versions,
    # State Physics
    "_custom_sp_state": _custom_sp_state,
    "_custom_sp_reset": _custom_sp_reset,
    "_custom_sp_nodes": _custom_sp_nodes,
    "_custom_sp_metrics": _custom_sp_metrics,
    "_custom_sp_identity": _custom_sp_identity,
    "_custom_sp_simulate": _custom_sp_simulate,
    "_custom_sp_galaxy": _custom_sp_galaxy,
    "_custom_sp_demo": _custom_sp_demo,
    "_custom_sp_asymmetry": _custom_sp_asymmetry,
    "_custom_sp_physics_config": _custom_sp_physics_config,
    "_custom_sp_entropy_config": _custom_sp_entropy_config,
    "_custom_sp_entropy_toggle": _custom_sp_entropy_toggle,
    "_custom_sp_entropy_perturbation": _custom_sp_entropy_perturbation,
    "_custom_sp_agent_spawn": _custom_sp_agent_spawn,
    "_custom_sp_agent_step": _custom_sp_agent_step,
    "_custom_sp_agent_kill": _custom_sp_agent_kill,
    "_custom_sp_agents_spawn": _custom_sp_agents_spawn,
    "_custom_sp_agents_kill_all": _custom_sp_agents_kill_all,
    "_custom_sp_experiment": _custom_sp_experiment,
    "_custom_sp_memory_cost": _custom_sp_memory_cost,
    "_custom_sp_metrics_record": _custom_sp_metrics_record,
    # Web search & browsing
    "_custom_web_search": _custom_web_search,
    "_custom_read_webpage": _custom_read_webpage,
    "_custom_read_many_pages": _custom_read_many_pages,
    "_custom_reddit_search": _custom_reddit_search,
    "_custom_news_search": _custom_news_search,
    # Dynamic tool management
    "_custom_create_tool": _custom_create_tool,
    "_custom_list_tools": _custom_list_tools,
    "_custom_delete_tool": _custom_delete_tool,
    "_custom_update_tool": _custom_update_tool,
    # System tools
    "_custom_get_current_time": _custom_get_current_time,
    "_custom_get_system_info": _custom_get_system_info,
    # GitHub API tools
    "_custom_github_create_repo": _custom_github_create_repo,
    "_custom_github_list_repos": _custom_github_list_repos,
    "_custom_github_list_files": _custom_github_list_files,
    "_custom_github_download_file": _custom_github_download_file,
    "_custom_github_upload_file": _custom_github_upload_file,
    "_custom_github_commits": _custom_github_commits,
    "_custom_github_pull_request": _custom_github_pull_request,
    "_custom_github_issue": _custom_github_issue,
    "_custom_github_comment": _custom_github_comment,
    "_custom_git_proxy": _custom_git_proxy,
    # Rabbit (Community Forum) tools
    "_custom_rabbit_create_community": _custom_rabbit_create_community,
    "_custom_rabbit_list_communities": _custom_rabbit_list_communities,
    "_custom_rabbit_get_community": _custom_rabbit_get_community,
    "_custom_rabbit_create_post": _custom_rabbit_create_post,
    "_custom_rabbit_list_posts": _custom_rabbit_list_posts,
    "_custom_rabbit_search_posts": _custom_rabbit_search_posts,
    "_custom_rabbit_get_post": _custom_rabbit_get_post,
    "_custom_rabbit_delete_post": _custom_rabbit_delete_post,
    "_custom_rabbit_create_comment": _custom_rabbit_create_comment,
    "_custom_rabbit_list_comments": _custom_rabbit_list_comments,
    "_custom_rabbit_delete_comment": _custom_rabbit_delete_comment,
    "_custom_rabbit_vote": _custom_rabbit_vote,
    # Utility tools
    "_custom_weather": _custom_weather,
    "_custom_image_search": _custom_image_search,
    "_custom_news_search": _custom_news_search,
    "_custom_places_search": _custom_places_search,
    "_custom_youtube_search": _custom_youtube_search,
    "_custom_stock_crypto": _custom_stock_crypto,
    "_custom_deep_research": _custom_deep_research,
    "_custom_generate_chart": _custom_generate_chart,
    "_custom_send_email": _custom_send_email,
    "_custom_wikipedia": _custom_wikipedia,
    "_custom_visualize": _custom_visualize,
    # Orchestrator tools
    "_custom_present_options": _custom_present_options,
    "_custom_workspace_snapshot": _custom_workspace_snapshot,
    "_custom_schedule_agent": _custom_schedule_agent,
    "_custom_run_snapshot": _custom_run_snapshot,
    "_custom_agent_snapshot": _custom_agent_snapshot,
    "_custom_run_agent": _custom_run_agent,
    "_custom_session_log": _custom_session_log,
}

# Build TOOL_DEFS from registry
if _HAS_REGISTRY:
    TOOL_DEFS: Dict[str, Any] = {
        t.name: {
            "handler": t.handler,
            "category": t.category.value if hasattr(t.category, 'value') else str(t.category),
        }
        for t in _registry.get_all()
    }
else:
    TOOL_DEFS: Dict[str, Any] = {}

logger.info(f"[REGISTRY] {len(TOOL_DEFS)} tools, {len(CUSTOM_HANDLERS)} handlers registered")

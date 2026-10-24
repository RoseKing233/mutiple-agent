using Dapper;
using Npgsql;

namespace ECommerceAgents.Orchestrator.Routes;

/// <summary>
/// Shared "fetch <c>agent_execution_steps</c> for one usage_log row" query,
/// used by both <see cref="AdminRoutes"/>'s <c>GET /api/admin/audit</c>
/// (admin-only, full filters) and <see cref="RunsRoutes"/>'s
/// <c>GET /api/runs</c> (any authenticated user, own-vs-admin scoped) —
/// Python's two equivalent endpoints (<c>routes.py:1297-1403</c> and
/// <c>:1406-1491</c>) select the identical step shape from the same table,
/// so this avoids duplicating that N+1 per-row query in both route files.
/// </summary>
internal static class UsageLogSteps
{
    public static async Task<List<object>> FetchAsync(NpgsqlConnection conn, Guid usageLogId)
    {
        return (await conn.QueryAsync(
            @"SELECT step_index, tool_name, tool_input, tool_output, status, duration_ms
              FROM agent_execution_steps
              WHERE usage_log_id = @id
              ORDER BY step_index",
            new { id = usageLogId }
        )).Select(s => (object)new
        {
            step_index = Convert.ToInt32(s.step_index),
            tool_name = (string?)s.tool_name,
            tool_input = (string?)s.tool_input?.ToString(),
            tool_output = (string?)s.tool_output?.ToString(),
            status = (string?)s.status,
            duration_ms = s.duration_ms is null ? (int?)null : Convert.ToInt32(s.duration_ms),
        }).ToList();
    }
}

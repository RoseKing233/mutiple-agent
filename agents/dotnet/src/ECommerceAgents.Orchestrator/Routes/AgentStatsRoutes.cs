using Dapper;
using ECommerceAgents.Shared.Context;
using ECommerceAgents.Shared.Data;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;

namespace ECommerceAgents.Orchestrator.Routes;

/// <summary>
/// <c>GET /api/agents/stats</c> — per-agent aggregate stats for the last 30
/// days, available to any authenticated user (not admin-gated). Mirrors
/// Python's <c>get_agent_stats</c> (<c>routes.py:1095-1117</c>). Previously
/// missing entirely from the .NET orchestrator.
/// </summary>
public static class AgentStatsRoutes
{
    public static IEndpointRouteBuilder MapAgentStatsRoutes(this IEndpointRouteBuilder routes)
    {
        routes.MapGet("/api/agents/stats", GetStats);
        return routes;
    }

    private static async Task<IResult> GetStats(DatabasePool pool)
    {
        if (string.IsNullOrEmpty(RequestContext.CurrentUserEmail))
        {
            return Results.Unauthorized();
        }

        await using var conn = await pool.OpenAsync();
        var rows = (await conn.QueryAsync(
            @"SELECT
                  agent_name,
                  COUNT(*) AS request_count,
                  AVG(duration_ms)::int AS avg_duration_ms,
                  COALESCE(SUM(tokens_in) + SUM(tokens_out), 0) AS total_tokens
              FROM usage_logs
              WHERE created_at >= NOW() - INTERVAL '30 days'
              GROUP BY agent_name"
        )).Select(r => new
        {
            agent_name = (string)r.agent_name,
            request_count = Convert.ToInt64(r.request_count),
            avg_duration_ms = r.avg_duration_ms is null ? 0 : Convert.ToInt32(r.avg_duration_ms),
            total_tokens = Convert.ToInt64(r.total_tokens),
        }).ToList();

        return Results.Ok(rows);
    }
}

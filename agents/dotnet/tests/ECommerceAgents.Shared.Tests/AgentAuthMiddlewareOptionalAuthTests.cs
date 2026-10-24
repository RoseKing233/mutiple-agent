using ECommerceAgents.Shared.Auth;
using ECommerceAgents.Shared.Configuration;
using ECommerceAgents.Shared.Context;
using FluentAssertions;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Xunit;

namespace ECommerceAgents.Shared.Tests;

/// <summary>
/// <see cref="AgentAuthMiddleware"/>'s optional-auth branch — the public
/// storefront surface (<c>/api/products</c>, <c>/api/chat</c>,
/// <c>/api/chat/stream</c>) mirrors Python's <c>optional_auth</c>
/// dependency: a missing Bearer token is anonymous, not a 401; a
/// present-but-invalid token still gets rejected normally. Maps synthetic
/// endpoints at the real paths so the middleware's own path-matching is
/// exercised exactly as it runs in production, without needing the actual
/// ProductRoutes/ChatRoutes handlers.
/// </summary>
public sealed class AgentAuthMiddlewareOptionalAuthTests
{
    private static AgentSettings SettingsFor() =>
        new()
        {
            AgentSharedSecret = new string('s', 48),
            JwtSecret = new string('j', 48),
            Environment = "test",
            AuthMode = "local",
        };

    private static TestServer BuildServer(AgentSettings settings, bool isOrchestrator = true)
    {
        var hostBuilder = new HostBuilder().ConfigureWebHost(web =>
        {
            web.UseTestServer();
            web.ConfigureServices(services =>
            {
                services.AddSingleton(settings);
                services.AddSingleton(new JwtTokenService(settings));
                services.AddSingleton(new JwksKeyProvider(new HttpClient(), settings));
                services.AddRouting();
            });
            web.Configure(app =>
            {
                app.UseAgentAuth(isOrchestrator);
                app.UseRouting();
                app.UseEndpoints(endpoints =>
                {
                    Task Echo(HttpContext ctx) => ctx.Response.WriteAsync(
                        JsonSerializer.Serialize(new
                        {
                            email = RequestContext.CurrentUserEmail,
                            role = RequestContext.CurrentUserRole,
                        })
                    );
                    endpoints.MapGet("/api/products", Echo);
                    endpoints.MapGet("/api/products/{id}", Echo);
                    endpoints.MapPost("/api/chat", Echo);
                    endpoints.MapPost("/api/chat/stream", Echo);
                    // Non-optional-auth route, for contrast in the same server.
                    endpoints.MapGet("/api/orders", Echo);
                });
            });
        });

        return hostBuilder.Start().GetTestServer();
    }

    [Theory]
    [InlineData("/api/products")]
    [InlineData("/api/products/11111111-1111-1111-1111-111111111111")]
    [InlineData("/api/chat")]
    [InlineData("/api/chat/stream")]
    public async Task NoAuthorizationHeader_OnOptionalAuthPath_IsAnonymousNot401(string path)
    {
        using var server = BuildServer(SettingsFor());
        using var client = server.CreateClient();

        var method = path.StartsWith("/api/chat", StringComparison.Ordinal) ? HttpMethod.Post : HttpMethod.Get;
        var response = await client.SendAsync(new HttpRequestMessage(method, path));

        response.StatusCode.Should().Be(HttpStatusCode.OK);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        body.GetProperty("email").GetString().Should().BeEmpty();
        body.GetProperty("role").GetString().Should().Be("anonymous");
    }

    [Fact]
    public async Task NoAuthorizationHeader_OnNonOptionalPath_StillRejected()
    {
        using var server = BuildServer(SettingsFor());
        using var client = server.CreateClient();

        var response = await client.GetAsync("/api/orders");

        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task ValidBearerToken_OnOptionalAuthPath_AuthenticatesNormally()
    {
        var settings = SettingsFor();
        var jwt = new JwtTokenService(settings);
        var token = jwt.IssueAccessToken("alice@example.com", "customer");
        using var server = BuildServer(settings);
        using var client = server.CreateClient();

        var request = new HttpRequestMessage(HttpMethod.Get, "/api/products");
        request.Headers.Add("Authorization", $"Bearer {token}");
        var response = await client.SendAsync(request);

        response.StatusCode.Should().Be(HttpStatusCode.OK);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        body.GetProperty("email").GetString().Should().Be("alice@example.com");
        body.GetProperty("role").GetString().Should().Be("customer");
    }

    [Fact]
    public async Task GarbageBearerToken_OnOptionalAuthPath_StillRejected()
    {
        // Only an ABSENT header is anonymous — a present-but-invalid token
        // must still 401, matching Python's optional_auth (which delegates
        // to require_auth whenever an Authorization header exists at all).
        using var server = BuildServer(SettingsFor());
        using var client = server.CreateClient();

        var request = new HttpRequestMessage(HttpMethod.Post, "/api/chat");
        request.Headers.Add("Authorization", "Bearer not-a-real-jwt");
        var response = await client.SendAsync(request);

        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }
}

using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using ECommerceAgents.Shared.Configuration;

namespace ECommerceAgents.Shared.Auth;

public sealed record AuthServerTokenResponse(
    [property: JsonPropertyName("access_token")] string AccessToken,
    [property: JsonPropertyName("refresh_token")] string? RefreshToken,
    [property: JsonPropertyName("token_type")] string TokenType,
    [property: JsonPropertyName("expires_in")] int? ExpiresIn,
    [property: JsonPropertyName("scope")] string? Scope
);

/// <summary>
/// HTTP client for the self-hosted auth-server's token endpoint
/// (<c>AuthMode=oauth</c>). Mirrors Python's
/// <c>shared/oauth/service_client.py::request_token</c> — backs the
/// orchestrator's login/refresh broker (Phase B) and inter-agent
/// client-credentials calls (Phase C, via <see cref="AcquireServiceTokenAsync"/>).
/// </summary>
public sealed class AuthServerClient(HttpClient httpClient, AgentSettings settings)
{
    private readonly HttpClient _httpClient = httpClient;
    private readonly AgentSettings _settings = settings;

    private static readonly TimeSpan RefreshSkew = TimeSpan.FromSeconds(30);

    // Process-wide, not instance-level: typed HttpClient registrations
    // (`AddHttpClient<AuthServerClient>()`) are resolved transiently, so a
    // new `AuthServerClient` can be constructed per call site. Caching must
    // survive that — mirrors Python's module-level `_service_token_cache`.
    private static readonly Dictionary<string, (string Token, DateTimeOffset ExpiresAt)> ServiceTokenCache = new();
    private static readonly SemaphoreSlim ServiceTokenLock = new(1, 1);

    /// <summary>
    /// POST to the auth-server's token endpoint as this service's own client.
    /// Throws <see cref="HttpRequestException"/> on a non-2xx response
    /// (invalid credentials, disallowed grant, etc.) — callers translate that
    /// into the appropriate user-facing error.
    /// </summary>
    public async Task<AuthServerTokenResponse> RequestTokenAsync(
        string grantType,
        IReadOnlyDictionary<string, string> form,
        CancellationToken ct = default
    )
    {
        var clientId = string.IsNullOrEmpty(_settings.OAuthClientId) ? "orchestrator" : _settings.OAuthClientId;
        var clientSecret = string.IsNullOrEmpty(_settings.OAuthClientSecret)
            ? ClientSecretDeriver.Derive(_settings.OAuthSeedKey, clientId)
            : _settings.OAuthClientSecret;

        var fields = new Dictionary<string, string>(form) { ["grant_type"] = grantType };
        using var request = new HttpRequestMessage(HttpMethod.Post, _settings.AuthServerTokenUrl)
        {
            Content = new FormUrlEncodedContent(fields),
        };
        request.Headers.Authorization = new AuthenticationHeaderValue(
            "Basic",
            Convert.ToBase64String(Encoding.UTF8.GetBytes($"{clientId}:{clientSecret}"))
        );

        var response = await _httpClient.SendAsync(request, ct);
        response.EnsureSuccessStatusCode();

        var json = await response.Content.ReadAsStringAsync(ct);
        return JsonSerializer.Deserialize<AuthServerTokenResponse>(json)
            ?? throw new InvalidOperationException("auth-server returned an empty token response");
    }

    /// <summary>
    /// Client-credentials grant against the AS, cached per <paramref name="scope"/>.
    /// Mirrors Python's <c>shared/oauth/service_client.py::acquire_service_token</c>
    /// — refreshes <see cref="RefreshSkew"/> before the cached token's expiry
    /// so a request already in flight never carries a token that expires
    /// mid-call.
    /// </summary>
    public async Task<string> AcquireServiceTokenAsync(string scope, CancellationToken ct = default)
    {
        if (
            ServiceTokenCache.TryGetValue(scope, out var cached)
            && DateTimeOffset.UtcNow < cached.ExpiresAt - RefreshSkew
        )
        {
            return cached.Token;
        }

        await ServiceTokenLock.WaitAsync(ct);
        try
        {
            // Another caller may have refreshed while we waited on the lock.
            if (
                ServiceTokenCache.TryGetValue(scope, out cached)
                && DateTimeOffset.UtcNow < cached.ExpiresAt - RefreshSkew
            )
            {
                return cached.Token;
            }

            var token = await RequestTokenAsync(
                "client_credentials",
                new Dictionary<string, string> { ["scope"] = scope },
                ct
            );
            var ttlSeconds = token.ExpiresIn ?? 3600;
            ServiceTokenCache[scope] = (token.AccessToken, DateTimeOffset.UtcNow.AddSeconds(ttlSeconds));
            return token.AccessToken;
        }
        finally
        {
            ServiceTokenLock.Release();
        }
    }
}

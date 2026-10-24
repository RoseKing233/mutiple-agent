using ECommerceAgents.Shared.Configuration;
using Microsoft.IdentityModel.Tokens;

namespace ECommerceAgents.Shared.Auth;

/// <summary>
/// Hand-rolled JWKS fetch-and-cache for validating RS256 tokens issued by
/// the self-hosted auth-server (<c>AuthMode=oauth</c>).
/// </summary>
/// <remarks>
/// Deliberately NOT <c>ConfigurationManager&lt;OpenIdConnectConfiguration&gt;</c> —
/// the auth-server serves RFC 8414 metadata
/// (<c>/.well-known/oauth-authorization-server</c>), not OIDC discovery
/// (<c>/.well-known/openid-configuration</c>), so that type's default
/// metadata-refresh path would 404. A plain <c>GET</c> of
/// <see cref="AgentSettings.AuthServerJwksUrl"/> plus a TTL cache is the
/// entire feature surface actually needed here.
/// </remarks>
public sealed class JwksKeyProvider(HttpClient httpClient, AgentSettings settings)
{
    private readonly HttpClient _httpClient = httpClient;
    private readonly AgentSettings _settings = settings;
    private readonly SemaphoreSlim _refreshLock = new(1, 1);

    private IReadOnlyList<SecurityKey>? _cachedKeys;
    private DateTimeOffset _cachedAt = DateTimeOffset.MinValue;

    public async Task<IReadOnlyList<SecurityKey>> GetSigningKeysAsync(CancellationToken ct = default)
    {
        var ttl = TimeSpan.FromSeconds(_settings.AuthJwksCacheTtl);
        if (_cachedKeys is not null && DateTimeOffset.UtcNow - _cachedAt < ttl)
        {
            return _cachedKeys;
        }

        await _refreshLock.WaitAsync(ct);
        try
        {
            // Another request may have refreshed the cache while we were
            // waiting for the lock — check again before hitting the network.
            if (_cachedKeys is not null && DateTimeOffset.UtcNow - _cachedAt < ttl)
            {
                return _cachedKeys;
            }

            var json = await _httpClient.GetStringAsync(_settings.AuthServerJwksUrl, ct);
            var jwks = new JsonWebKeySet(json);
            _cachedKeys = jwks.Keys.Cast<SecurityKey>().ToList();
            _cachedAt = DateTimeOffset.UtcNow;
            return _cachedKeys;
        }
        finally
        {
            _refreshLock.Release();
        }
    }
}

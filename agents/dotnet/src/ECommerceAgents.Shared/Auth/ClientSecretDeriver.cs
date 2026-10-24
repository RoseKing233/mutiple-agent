using System.Security.Cryptography;
using System.Text;

namespace ECommerceAgents.Shared.Auth;

/// <summary>
/// Deterministic dev client-secret derivation — mirrors Python's
/// <c>shared/oauth/client_secrets.py::derive_client_secret</c> exactly
/// (HMAC-SHA256 of <c>client_id</c> keyed by <c>OAUTH_SEED_KEY</c>, hex-encoded)
/// so both stacks compute the identical secret from one shared seed without
/// a secrets round-trip. Production deployments override
/// <c>OAuthClientSecret</c> per service instead of relying on this derivation.
/// </summary>
public static class ClientSecretDeriver
{
    public static string Derive(string seedKey, string clientId)
    {
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(seedKey));
        var hash = hmac.ComputeHash(Encoding.UTF8.GetBytes(clientId));
        return Convert.ToHexStringLower(hash);
    }
}

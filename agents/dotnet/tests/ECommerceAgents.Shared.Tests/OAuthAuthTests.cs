using ECommerceAgents.Shared.Auth;
using ECommerceAgents.Shared.Configuration;
using FluentAssertions;
using Microsoft.IdentityModel.Tokens;
using System.IdentityModel.Tokens.Jwt;
using System.Net;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using Xunit;

namespace ECommerceAgents.Shared.Tests;

/// <summary>
/// Covers the .NET half of Phase B (self-hosted OAuth2 Authorization Server
/// integration): RS256 validation against a JWKS, JWKS fetch/cache, deriving
/// the shared dev client-secret, and brokering token requests to the AS.
/// </summary>
public sealed class OAuthAuthTests
{
    private static AgentSettings SettingsFor(string issuer) => new()
    {
        AgentSharedSecret = new string('s', 48),
        JwtSecret = new string('j', 48),
        Environment = "test",
        AuthServerIssuer = issuer,
    };

    // ─────────────────────── ClientSecretDeriver ─────────────

    [Fact]
    public void ClientSecretDeriver_MatchesPythonReferenceVector()
    {
        // Cross-checked against Python's shared/oauth/client_secrets.py::derive_client_secret
        // via: hmac.new(b"dev-oauth-seed-change-me", b"orchestrator", sha256).hexdigest()
        var secret = ClientSecretDeriver.Derive("dev-oauth-seed-change-me", "orchestrator");
        secret.Should().Be("d8def614d6406dc8f8600aeb3231209ba4538e9bac6b6128adcbe8e6247b9467");
    }

    [Fact]
    public void ClientSecretDeriver_DifferentClientIdsProduceDifferentSecrets()
    {
        var a = ClientSecretDeriver.Derive("seed", "orchestrator");
        var b = ClientSecretDeriver.Derive("seed", "product-discovery");
        a.Should().NotBe(b);
    }

    // ─────────────────────── JwtTokenService.ValidateOAuth ───

    private static (RsaSecurityKey key, string kid) NewRsaKey()
    {
        var rsa = RSA.Create(2048);
        var kid = Guid.NewGuid().ToString("N");
        return (new RsaSecurityKey(rsa) { KeyId = kid }, kid);
    }

    private static string IssueTestToken(
        RsaSecurityKey key,
        string issuer,
        string audience,
        string scope,
        DateTime? expires = null
    )
    {
        var handler = new JwtSecurityTokenHandler();
        var creds = new SigningCredentials(key, SecurityAlgorithms.RsaSha256);
        var token = new JwtSecurityToken(
            issuer: issuer,
            audience: audience,
            claims: new[]
            {
                new Claim("sub", "alice@example.com"),
                new Claim("scope", scope),
                new Claim("role", "customer"),
            },
            notBefore: DateTime.UtcNow.AddMinutes(-30),
            expires: expires ?? DateTime.UtcNow.AddMinutes(5),
            signingCredentials: creds
        );
        return handler.WriteToken(token);
    }

    [Fact]
    public void ValidateOAuth_AcceptsCorrectlySignedTokenWithRequiredScope()
    {
        var (key, _) = NewRsaKey();
        var settings = SettingsFor("http://auth-server:8090");
        var jwt = new JwtTokenService(settings);
        var token = IssueTestToken(key, settings.AuthServerIssuer, "ecommerce-orchestrator", "api:chat");

        var principal = jwt.ValidateOAuth(token, new[] { (SecurityKey)key }, "ecommerce-orchestrator", "api:chat");

        principal.FindFirst("sub")!.Value.Should().Be("alice@example.com");
    }

    [Fact]
    public void ValidateOAuth_RejectsWrongAudience()
    {
        var (key, _) = NewRsaKey();
        var settings = SettingsFor("http://auth-server:8090");
        var jwt = new JwtTokenService(settings);
        var token = IssueTestToken(key, settings.AuthServerIssuer, "ecommerce-agents", "agent:invoke");

        var act = () => jwt.ValidateOAuth(token, new[] { (SecurityKey)key }, "ecommerce-orchestrator");
        act.Should().Throw<SecurityTokenException>();
    }

    [Fact]
    public void ValidateOAuth_RejectsWrongIssuer()
    {
        var (key, _) = NewRsaKey();
        var settings = SettingsFor("http://auth-server:8090");
        var jwt = new JwtTokenService(settings);
        var token = IssueTestToken(key, "http://someone-else:9999", "ecommerce-orchestrator", "api:chat");

        var act = () => jwt.ValidateOAuth(token, new[] { (SecurityKey)key }, "ecommerce-orchestrator");
        act.Should().Throw<SecurityTokenException>();
    }

    [Fact]
    public void ValidateOAuth_RejectsExpiredToken()
    {
        var (key, _) = NewRsaKey();
        var settings = SettingsFor("http://auth-server:8090");
        var jwt = new JwtTokenService(settings);
        var token = IssueTestToken(
            key,
            settings.AuthServerIssuer,
            "ecommerce-orchestrator",
            "api:chat",
            expires: DateTime.UtcNow.AddMinutes(-10)
        );

        var act = () => jwt.ValidateOAuth(token, new[] { (SecurityKey)key }, "ecommerce-orchestrator");
        act.Should().Throw<SecurityTokenException>();
    }

    [Fact]
    public void ValidateOAuth_RejectsMissingRequiredScope()
    {
        var (key, _) = NewRsaKey();
        var settings = SettingsFor("http://auth-server:8090");
        var jwt = new JwtTokenService(settings);
        var token = IssueTestToken(key, settings.AuthServerIssuer, "ecommerce-orchestrator", "agent:invoke");

        var act = () => jwt.ValidateOAuth(token, new[] { (SecurityKey)key }, "ecommerce-orchestrator", "api:chat");
        act.Should().Throw<SecurityTokenException>().WithMessage("*required scope*");
    }

    [Fact]
    public void ValidateOAuth_RejectsTokenSignedByUnknownKey()
    {
        var (signingKey, _) = NewRsaKey();
        var (otherKey, _) = NewRsaKey(); // deliberately not in the trusted set passed to ValidateOAuth
        var settings = SettingsFor("http://auth-server:8090");
        var jwt = new JwtTokenService(settings);
        var token = IssueTestToken(signingKey, settings.AuthServerIssuer, "ecommerce-orchestrator", "api:chat");

        var act = () => jwt.ValidateOAuth(token, new[] { (SecurityKey)otherKey }, "ecommerce-orchestrator");
        act.Should().Throw<SecurityTokenException>();
    }

    // ─────────────────────── JwksKeyProvider ─────────────────

    private static string BuildJwksJson(RsaSecurityKey key)
    {
        var parameters = key.Rsa!.ExportParameters(false);
        var n = Base64UrlEncoder.Encode(parameters.Modulus);
        var e = Base64UrlEncoder.Encode(parameters.Exponent);
        return $$"""{"keys":[{"kty":"RSA","use":"sig","kid":"{{key.KeyId}}","alg":"RS256","n":"{{n}}","e":"{{e}}"}]}""";
    }

    private sealed class CountingHandler(Func<string> bodyFactory) : HttpMessageHandler
    {
        public int CallCount { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            CallCount++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(bodyFactory(), Encoding.UTF8, "application/json"),
            });
        }
    }

    [Fact]
    public async Task JwksKeyProvider_FetchesAndParsesKeys()
    {
        var (key, _) = NewRsaKey();
        var handler = new CountingHandler(() => BuildJwksJson(key));
        var settings = SettingsFor("http://auth-server:8090") with { AuthJwksCacheTtl = 900 };
        var provider = new JwksKeyProvider(new HttpClient(handler), settings);

        var keys = await provider.GetSigningKeysAsync();

        keys.Should().HaveCount(1);
        handler.CallCount.Should().Be(1);
    }

    [Fact]
    public async Task JwksKeyProvider_CachesWithinTtl()
    {
        var (key, _) = NewRsaKey();
        var handler = new CountingHandler(() => BuildJwksJson(key));
        var settings = SettingsFor("http://auth-server:8090") with { AuthJwksCacheTtl = 900 };
        var provider = new JwksKeyProvider(new HttpClient(handler), settings);

        await provider.GetSigningKeysAsync();
        await provider.GetSigningKeysAsync();
        await provider.GetSigningKeysAsync();

        handler.CallCount.Should().Be(1);
    }

    [Fact]
    public async Task JwksKeyProvider_RefreshesAfterTtlExpires()
    {
        var (key, _) = NewRsaKey();
        var handler = new CountingHandler(() => BuildJwksJson(key));
        var settings = SettingsFor("http://auth-server:8090") with { AuthJwksCacheTtl = 0 };
        var provider = new JwksKeyProvider(new HttpClient(handler), settings);

        await provider.GetSigningKeysAsync();
        await provider.GetSigningKeysAsync();

        handler.CallCount.Should().Be(2);
    }

    // ─────────────────────── AuthServerClient ────────────────

    private sealed class RecordingHandler(HttpStatusCode status, string body) : HttpMessageHandler
    {
        public HttpRequestMessage? LastRequest { get; private set; }
        public string? LastRequestBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            LastRequest = request;
            LastRequestBody = request.Content is null ? null : await request.Content.ReadAsStringAsync(ct);
            return new HttpResponseMessage(status)
            {
                Content = new StringContent(body, Encoding.UTF8, "application/json"),
            };
        }
    }

    [Fact]
    public async Task AuthServerClient_SendsBasicAuthAndGrantFields()
    {
        var handler = new RecordingHandler(
            HttpStatusCode.OK,
            """{"access_token":"at","refresh_token":"rt","token_type":"Bearer","expires_in":3600,"scope":"api:chat"}"""
        );
        var settings = SettingsFor("http://auth-server:8090") with
        {
            AuthServerTokenUrl = "http://auth-server:8090/oauth/token",
            OAuthClientId = "orchestrator",
            OAuthSeedKey = "dev-oauth-seed-change-me",
        };
        var client = new AuthServerClient(new HttpClient(handler), settings);

        var token = await client.RequestTokenAsync(
            "password",
            new Dictionary<string, string> { ["username"] = "alice@example.com", ["password"] = "secret" }
        );

        token.AccessToken.Should().Be("at");
        token.RefreshToken.Should().Be("rt");

        handler.LastRequest!.Headers.Authorization!.Scheme.Should().Be("Basic");
        var expectedSecret = ClientSecretDeriver.Derive("dev-oauth-seed-change-me", "orchestrator");
        var expectedHeader = Convert.ToBase64String(Encoding.UTF8.GetBytes($"orchestrator:{expectedSecret}"));
        handler.LastRequest.Headers.Authorization.Parameter.Should().Be(expectedHeader);

        handler.LastRequestBody.Should().Contain("grant_type=password");
        handler.LastRequestBody.Should().Contain("username=alice%40example.com");
    }

    [Fact]
    public async Task AuthServerClient_ThrowsOnNon2xxResponse()
    {
        var handler = new RecordingHandler(HttpStatusCode.Unauthorized, """{"error":"invalid_grant"}""");
        var settings = SettingsFor("http://auth-server:8090") with
        {
            AuthServerTokenUrl = "http://auth-server:8090/oauth/token",
        };
        var client = new AuthServerClient(new HttpClient(handler), settings);

        var act = async () =>
            await client.RequestTokenAsync(
                "password",
                new Dictionary<string, string> { ["username"] = "alice@example.com", ["password"] = "wrong" }
            );

        await act.Should().ThrowAsync<HttpRequestException>();
    }

    [Fact]
    public async Task AuthServerClient_PrefersExplicitClientSecretOverDerivedOne()
    {
        var handler = new RecordingHandler(
            HttpStatusCode.OK,
            """{"access_token":"at","refresh_token":null,"token_type":"Bearer","expires_in":3600,"scope":"agent:invoke"}"""
        );
        var settings = SettingsFor("http://auth-server:8090") with
        {
            AuthServerTokenUrl = "http://auth-server:8090/oauth/token",
            OAuthClientId = "orchestrator",
            OAuthClientSecret = "explicit-prod-secret",
        };
        var client = new AuthServerClient(new HttpClient(handler), settings);

        await client.RequestTokenAsync("client_credentials", new Dictionary<string, string>());

        var expectedHeader = Convert.ToBase64String(Encoding.UTF8.GetBytes("orchestrator:explicit-prod-secret"));
        handler.LastRequest!.Headers.Authorization!.Parameter.Should().Be(expectedHeader);
    }

    // ─────────────────────── AcquireServiceTokenAsync (Phase C) ──────
    // The cache is process-wide (static), not per-instance — each test uses
    // its own unique scope string as the cache key so tests never collide.

    private sealed class CountingTokenHandler(Func<string> bodyFactory) : HttpMessageHandler
    {
        public int CallCount { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            CallCount++;
            return Task.FromResult(
                new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(bodyFactory(), Encoding.UTF8, "application/json"),
                }
            );
        }
    }

    [Fact]
    public async Task AcquireServiceToken_CachesWithinTtl()
    {
        var handler = new CountingTokenHandler(() =>
            """{"access_token":"svc-tok","token_type":"Bearer","expires_in":3600}"""
        );
        var client = new AuthServerClient(new HttpClient(handler), SettingsFor("http://auth-server:8090"));
        var scope = $"test-scope-{Guid.NewGuid():N}";

        var first = await client.AcquireServiceTokenAsync(scope);
        var second = await client.AcquireServiceTokenAsync(scope);

        first.Should().Be("svc-tok");
        second.Should().Be("svc-tok");
        handler.CallCount.Should().Be(1);
    }

    [Fact]
    public async Task AcquireServiceToken_DistinctScopesCachedIndependently()
    {
        var issued = new Queue<string>(new[] { "tok-a", "tok-b" });
        var handler = new CountingTokenHandler(() => $$"""{"access_token":"{{issued.Dequeue()}}","expires_in":3600}""");
        var client = new AuthServerClient(new HttpClient(handler), SettingsFor("http://auth-server:8090"));
        var scopeA = $"test-scope-a-{Guid.NewGuid():N}";
        var scopeB = $"test-scope-b-{Guid.NewGuid():N}";

        var tokenA = await client.AcquireServiceTokenAsync(scopeA);
        var tokenB = await client.AcquireServiceTokenAsync(scopeB);

        tokenA.Should().Be("tok-a");
        tokenB.Should().Be("tok-b");
        handler.CallCount.Should().Be(2);
    }

    [Fact]
    public async Task AcquireServiceToken_RefreshesAfterExpiryWithSkew()
    {
        var callCount = 0;
        var handler = new CountingTokenHandler(() =>
        {
            callCount++;
            // expires_in=0 means the token is immediately inside the 30s
            // refresh-skew window, forcing every call to re-fetch.
            return $$"""{"access_token":"tok-{{callCount}}","expires_in":0}""";
        });
        var client = new AuthServerClient(new HttpClient(handler), SettingsFor("http://auth-server:8090"));
        var scope = $"test-scope-{Guid.NewGuid():N}";

        var first = await client.AcquireServiceTokenAsync(scope);
        var second = await client.AcquireServiceTokenAsync(scope);

        first.Should().Be("tok-1");
        second.Should().Be("tok-2");
        handler.CallCount.Should().Be(2);
    }

    [Fact]
    public async Task AcquireServiceToken_DefaultsTtlWhenAsOmitsExpiresIn()
    {
        var handler = new CountingTokenHandler(() => """{"access_token":"tok-no-ttl"}""");
        var client = new AuthServerClient(new HttpClient(handler), SettingsFor("http://auth-server:8090"));
        var scope = $"test-scope-{Guid.NewGuid():N}";

        var token = await client.AcquireServiceTokenAsync(scope);

        token.Should().Be("tok-no-ttl");
    }

    [Fact]
    public async Task AcquireServiceToken_SendsClientCredentialsGrantWithScope()
    {
        var handler = new RecordingHandler(
            HttpStatusCode.OK,
            """{"access_token":"tok","expires_in":3600}"""
        );
        var client = new AuthServerClient(new HttpClient(handler), SettingsFor("http://auth-server:8090"));
        var scope = $"test-scope-{Guid.NewGuid():N}";

        await client.AcquireServiceTokenAsync(scope);

        handler.LastRequestBody.Should().Contain("grant_type=client_credentials");
        handler.LastRequestBody.Should().Contain($"scope={scope}");
    }
}

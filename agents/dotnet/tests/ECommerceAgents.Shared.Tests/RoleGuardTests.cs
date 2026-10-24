using ECommerceAgents.Shared.Configuration;
using ECommerceAgents.Shared.Context;
using ECommerceAgents.Shared.Guardrails;
using FluentAssertions;
using Xunit;

namespace ECommerceAgents.Shared.Tests;

/// <summary>
/// Unit tests for <see cref="RoleGuard"/> — the .NET counterpart of Python's
/// <c>shared/guardrails/roles.py::ensure_role</c>. No DB, no LLM: this is a
/// pure ContextVar/AsyncLocal read plus a set-membership check.
/// </summary>
public sealed class RoleGuardTests : IDisposable
{
    public RoleGuardTests()
    {
        // Every test starts from a clean slate — AsyncLocal doesn't reset
        // itself between tests in the same collection.
        RequestContext.CurrentUserRole = "";
    }

    public void Dispose() => RequestContext.CurrentUserRole = "";

    [Fact]
    public void Ensure_AllowsListedRole()
    {
        RequestContext.CurrentUserRole = "seller";
        RoleGuard.Ensure(new AgentSettings { GuardrailsEnabled = true }, "seller", "admin").Should().BeNull();
    }

    [Fact]
    public void Ensure_AdminAlwaysAllowed()
    {
        RequestContext.CurrentUserRole = "admin";
        RoleGuard.Ensure(new AgentSettings { GuardrailsEnabled = true }, "seller").Should().BeNull();
    }

    [Fact]
    public void Ensure_DeniesUnlistedRole()
    {
        RequestContext.CurrentUserRole = "customer";
        var denied = RoleGuard.Ensure(new AgentSettings { GuardrailsEnabled = true }, "seller", "admin");
        denied.Should().NotBeNull();
        denied.Should().Contain("seller");
    }

    [Fact]
    public void Ensure_DeniesMissingRole()
    {
        RequestContext.CurrentUserRole = "";
        RoleGuard.Ensure(new AgentSettings { GuardrailsEnabled = true }, "seller", "admin").Should().NotBeNull();
    }

    [Fact]
    public void Ensure_DisabledBypasses()
    {
        RequestContext.CurrentUserRole = "customer";
        RoleGuard.Ensure(new AgentSettings { GuardrailsEnabled = false }, "seller", "admin").Should().BeNull();
    }

    [Fact]
    public void Ensure_IsCaseInsensitive()
    {
        RequestContext.CurrentUserRole = "SELLER";
        RoleGuard.Ensure(new AgentSettings { GuardrailsEnabled = true }, "seller", "admin").Should().BeNull();
    }
}

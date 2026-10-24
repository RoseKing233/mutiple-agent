using ECommerceAgents.Shared.Prompts;
using FluentAssertions;
using Xunit;

namespace ECommerceAgents.Shared.Tests;

/// <summary>
/// Guards the agent-name → prompt-file wiring. Every .NET agent previously passed
/// a snake_case name ("product_discovery") while the shared YAML files are
/// kebab-case ("product-discovery.yaml"), and <see cref="PromptLoader"/> answered a
/// missing file with <c>string.Empty</c> — so all five specialists ran with no
/// system prompt at all (no grounding rules, no rich-card formatting, no role
/// confinement) and still produced plausible-looking answers. These tests pin both
/// halves: the real names resolve, and a bad name throws instead of degrading.
/// </summary>
public sealed class PromptLoaderTests
{
    /// <summary>The exact names the agents pass to <c>SpecialistAgentFactory.Create</c>.</summary>
    public static TheoryData<string> AgentNames() => new()
    {
        "orchestrator",
        "product-discovery",
        "order-management",
        "pricing-promotions",
        "review-sentiment",
        "inventory-fulfillment",
    };

    private static string PromptsRoot()
    {
        var dir = new DirectoryInfo(Directory.GetCurrentDirectory());
        while (dir is not null && !Directory.Exists(Path.Combine(dir.FullName, "agents", "python", "config", "prompts")))
        {
            dir = dir.Parent;
        }
        dir.Should().NotBeNull("the shared prompts directory must be locatable from the test working directory");
        return Path.Combine(dir!.FullName, "agents", "python", "config", "prompts");
    }

    [Theory]
    [MemberData(nameof(AgentNames))]
    public void Load_ResolvesEveryAgentNameToANonEmptyPrompt(string agentName)
    {
        var loader = new PromptLoader(PromptsRoot());

        var prompt = loader.Load(agentName);

        prompt.Should().NotBeNullOrWhiteSpace();
        // The shared grounding rules are composed into every agent's prompt — their
        // absence is exactly the silent failure this test exists to catch.
        prompt.Should().Contain("Data Grounding Rules");
    }

    [Theory]
    [MemberData(nameof(AgentNames))]
    public void Load_IncludesRichCardFormattingForEveryAgent(string agentName)
    {
        var loader = new PromptLoader(PromptsRoot());

        var prompt = loader.Load(agentName);

        // Without this section specialists emit prose only, the orchestrator has no
        // card to relay, and the UI loses product/order cards entirely.
        prompt.Should().Contain("Rich Cards");
    }

    [Fact]
    public void Load_ThrowsForUnknownAgentNameInsteadOfReturningEmptyPrompt()
    {
        var loader = new PromptLoader(PromptsRoot());

        // The snake_case spelling that silently produced an empty prompt.
        var act = () => loader.Load("product_discovery");

        act.Should().Throw<FileNotFoundException>().WithMessage("*product_discovery*");
    }
}

using ECommerceAgents.Shared.Agents;
using ECommerceAgents.Shared.Configuration;
using FluentAssertions;
using Microsoft.Extensions.AI;
using Xunit;

namespace ECommerceAgents.Shared.Tests;

/// <summary>
/// <see cref="SpecialistAgentFactory.BuildOptions"/> — the construction-time
/// options every orchestrator/specialist agent gets built with. Covers Part C
/// (temperature parity): Python pins <c>LLM_TEMPERATURE</c> on every run
/// (<c>shared/agent_host.py::_run_options</c>); .NET wires the equivalent
/// through <see cref="AgentSettings.Temperature"/> once at agent-construction
/// time via <c>ChatClientAgentOptions.ChatOptions.Temperature</c>.
/// </summary>
public sealed class SpecialistAgentFactoryTests
{
    [Fact]
    public void BuildOptions_SetsTemperatureFromSettings()
    {
        var settings = new AgentSettings { Temperature = 0.2 };

        var options = SpecialistAgentFactory.BuildOptions(settings, "be helpful", "order-management");

        options.ChatOptions!.Temperature.Should().Be(0.2f);
    }

    [Fact]
    public void BuildOptions_RespectsNonDefaultTemperature()
    {
        var settings = new AgentSettings { Temperature = 0.9 };

        var options = SpecialistAgentFactory.BuildOptions(settings, "be helpful", "order-management");

        options.ChatOptions!.Temperature.Should().Be(0.9f);
    }

    [Fact]
    public void BuildOptions_SetsInstructionsAndName()
    {
        var settings = new AgentSettings();

        var options = SpecialistAgentFactory.BuildOptions(settings, "be helpful", "order-management");

        options.Name.Should().Be("order-management");
        options.ChatOptions!.Instructions.Should().Be("be helpful");
    }

    [Fact]
    public void BuildOptions_AttachesToolsWhenProvided()
    {
        var settings = new AgentSettings();
        var tool = AIFunctionFactory.Create(() => "ok", "noop_tool");

        var options = SpecialistAgentFactory.BuildOptions(settings, "be helpful", "order-management", new[] { tool });

        options.ChatOptions!.Tools.Should().ContainSingle(t => t.Name == "noop_tool");
    }

    [Fact]
    public void BuildOptions_LeavesToolsNullWhenNoneProvided()
    {
        var settings = new AgentSettings();

        var options = SpecialistAgentFactory.BuildOptions(settings, "be helpful", "order-management");

        options.ChatOptions!.Tools.Should().BeNull();
    }
}

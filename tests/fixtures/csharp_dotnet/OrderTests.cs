using Xunit;
using Sample.Application;

namespace Sample.Tests;

public sealed class OrderTests
{
    [Fact]
    public async Task Handler_uses_service() { await new OrderHandler(null!).Handle(new OrderRequest(1), default); }
}

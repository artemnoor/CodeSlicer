using MediatR;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Sample.Application;

public interface IOrderService { Task Handle(OrderRequest request); }
public sealed record OrderRequest(int Id) : IRequest;
public sealed class OrderHandler : IRequestHandler<OrderRequest>
{
    private readonly IOrderService service;
    public OrderHandler(IOrderService service) { this.service = service; }
    public async Task Handle(OrderRequest request, CancellationToken token) { await service.Handle(request); }
}
public sealed class OrderService : IOrderService
{
    private readonly SampleDbContext db;
    public OrderService(SampleDbContext db) { this.db = db; }
    public Task Handle(OrderRequest request) { return db.Orders.AnyAsync(); }
}
public sealed class Order { public int Id { get; set; } }
public sealed class SampleDbContext : DbContext
{
    public DbSet<Order> Orders => Set<Order>();
}
public static class CompositionRoot
{
    public static void Configure(IServiceCollection services)
    {
        services.AddScoped<IOrderService, OrderService>();
    }
}

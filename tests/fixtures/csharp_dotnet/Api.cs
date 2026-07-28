using Microsoft.AspNetCore.Mvc;
using MediatR;

namespace Sample.Api;

[ApiController]
[Route("api/orders")]
public sealed class OrdersController : ControllerBase
{
    private readonly ISender sender;
    public OrdersController(ISender sender) { this.sender = sender; }
    [HttpGet("{id}")]
    public Task Get(int id) => sender.Send(new Sample.Application.OrderRequest(id));
}

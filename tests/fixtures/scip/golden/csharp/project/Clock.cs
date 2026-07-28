namespace Golden;

public interface IClock
{
    string Now();
}

public sealed class SystemClock : IClock
{
    public string Now() => "now";
}

public static class Consumer
{
    public static string ReadNow(IClock clock)
    {
        var marker = "🚀";
        return clock.Now();
    }
}

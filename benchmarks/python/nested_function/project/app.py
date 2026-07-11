def outer(value):
    def helper(item): return item
    return helper(value)

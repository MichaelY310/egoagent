def moving_average(values, window):
    """Return averages for every complete sliding window."""
    if not isinstance(window, int) or window <= 0:
        raise ValueError("window must be a positive integer")
    if window > len(values):
        return []
    return [sum(values[index:index + window]) / window for index in range(len(values) - window)]

"""Choose workers from available CPUs, with an explicit override for small runs."""
import os


def worker_count(value='auto', *, tasks=None):
    if value == 'auto':
        count = getattr(os, 'process_cpu_count', os.cpu_count)() or 1
    else:
        count = int(value)
        if count < 1:
            raise ValueError('workers must be auto or a positive integer')
    if tasks is not None:
        count = min(count, max(1, tasks))
    return count

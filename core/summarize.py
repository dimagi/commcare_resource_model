from collections import namedtuple

import pandas as pd

from core.utils import format_date, bytes_to_gb

StorageSummary = namedtuple('StorageSummary', 'by_category by_group')
SummaryComparison = namedtuple('SummaryComparison', 'storage_by_category storage_by_group compute')


def compare_summaries(summaries_by_date):
    storage_by_cat_series = []
    storage_by_group_series = []
    compute_series = []
    dates = sorted(list(summaries_by_date))
    for date in dates:
        summary_data = summaries_by_date[date]
        storage_by_cat_series.append(summary_data.storage.by_category['Total (GB)'])
        storage_by_group_series.append(summary_data.storage.by_group['Total (GB)'])
        compute_series.append(summary_data.compute[['CPU Total', 'RAM Total', 'VMs Total']])

    keys = [format_date(date) for date in dates]
    storage_by_cat = pd.concat(storage_by_cat_series, axis=1, keys=keys)
    storage_by_group = pd.concat(storage_by_group_series, axis=1, keys=keys)
    compute = pd.concat(compute_series, axis=1, keys=keys)
    return SummaryComparison(storage_by_cat, storage_by_group, compute)


def summarize_storage_data(config, summary_date, storage_data):
    storage_snapshot = storage_data.loc[summary_date]
    storage_by_cat = pd.DataFrame({
        'Size': storage_snapshot.map(bytes_to_gb),
        'Buffer': (storage_snapshot * float(config.buffer)).map(bytes_to_gb),
        'Total (GB)': (storage_snapshot * (1 + float(config.buffer))).map(bytes_to_gb),
        'total_raw': (storage_snapshot * (1 + float(config.buffer))),
        'Group': pd.Series({
            storage_key: storage_conf.group
            for storage_key, storage_conf in config.storage.items()
        })
    })

    by_type = storage_by_cat.groupby('Group')['total_raw'].sum()
    by_type.index.name = None
    storage_by_group = pd.DataFrame({
        'Total (GB)': by_type.map(bytes_to_gb),
    })

    storage_by_cat.sort_index(inplace=True)
    storage_by_group.sort_index(inplace=True)
    return StorageSummary(storage_by_cat, storage_by_group)


def summarize_compute_data(config, summary_date, compute_data):
    compute_snapshot = compute_data.loc[summary_date]
    unstacked = compute_snapshot.unstack()
    buffer = unstacked * float(config.buffer)
    total = unstacked.add(buffer)

    buffer = buffer.rename({col: '%s Buffer' % col for col in buffer.columns}, axis=1)
    buffer = buffer.astype(int)
    total = total.rename({col: '%s Total' % col for col in total.columns}, axis=1)
    total = total.astype(int)

    unstacked = unstacked.astype(int)
    combined = pd.concat([unstacked, buffer, total], axis=1)
    combined = combined.reindex(columns=sorted(list(combined.columns)))
    combined.sort_index(inplace=True)
    return combined
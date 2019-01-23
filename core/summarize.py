import math
from collections import namedtuple, OrderedDict

import pandas as pd
import numpy as np

from core.utils import format_date, to_storage_display_unit, tenth_round

ServiceSummary = namedtuple('ServiceSummary', 'service_summary storage_by_group')
SummaryComparison = namedtuple('SummaryComparison', 'storage_by_category storage_by_group compute')


def incremental_summaries(summary_comparisons, summary_dates):
    storage_by_cat_series = []
    storage_by_group_series = []
    compute_series = []
    keys = [format_date(date) for date in summary_dates]

    def _get_incremental(loop_count, keys, data):
        key = keys[loop_count]
        if loop_count == 0:
            return data[key]
        else:
            previous_key = keys[loop_count - 1]
            return data[key] - data[previous_key]

    for i, key in enumerate(keys):
        storage_by_cat_series.append(_get_incremental(i, keys, summary_comparisons.storage_by_category))
        storage_by_group_series.append(_get_incremental(i, keys, summary_comparisons.storage_by_group))
        compute_series.append(_get_incremental(i, keys, summary_comparisons.compute))

    storage_by_cat_series.append(summary_comparisons.storage_by_category['Group'])
    return SummaryComparison(
        pd.concat(storage_by_cat_series, axis=1, keys=keys + ['Group']),
        pd.concat(storage_by_group_series, axis=1, keys=keys),
        pd.concat(compute_series, axis=1, keys=keys),
    )


def summarize_service_data(config, summary_data, summary_date):
    storage_units = config.storage_display_unit
    to_display = to_storage_display_unit(storage_units)

    summary_by_service = summary_data[:, summary_date].T
    summary_by_service.sort_index(inplace=True)

    by_type = summary_by_service.groupby('Storage Group')['Data Storage Total (%s)' % storage_units].sum()
    if config.vm_os_storage_group not in by_type:
        by_type[config.vm_os_storage_group] = 0
    by_type[config.vm_os_storage_group] += math.ceil(to_display(summary_by_service['OS Storage Total (Bytes)'].sum()))

    by_type.index.name = None
    storage_by_group = pd.DataFrame({
        'Rounded Total (%s)' % storage_units: by_type,
    })

    summary_by_service.drop('OS Storage Total (Bytes)', axis=1, inplace=True)
    total = summary_by_service.sum()
    total.name = 'Total'
    summary_by_service = summary_by_service.append(total, ignore_index=False)

    storage_by_group.sort_index(inplace=True)
    return ServiceSummary(summary_by_service, storage_by_group)


def get_summary_data(config, service_data):
    """Compute summary data for each month and each service"""

    # formula for compound growth: start_val * (1 + growth factor)^N
    ebi = pd.Series(range(0, len(service_data.index)), index=service_data.index)
    estimation_buffer = config.estimation_buffer * (1 + config.estimation_growth_factor) ** ebi
    estimation_buffer = estimation_buffer.map(float)

    storage_units = config.storage_display_unit
    to_display = to_storage_display_unit(storage_units)
    to_gb = to_storage_display_unit('GB')
    summary_df = dict()
    for service_name, service_def in config.services.items():
        service_snapshot = service_data[service_name]
        compute = service_snapshot['Compute']
        data_storage = service_snapshot['Data Storage']['storage']
        node_buffer = 0 if service_def.static_number else (compute['VMs'] * estimation_buffer).map(np.ceil)
        vms_suggested = (compute['VMs'] + node_buffer).map(np.ceil)
        vms_total = pd.DataFrame([
            vms_suggested,
            pd.Series([service_def.min_nodes] * len(vms_suggested), index=vms_suggested.index)
        ]).max()

        storage_estimation_buffer = estimation_buffer
        if service_def.storage.override_estimation_buffer is not None:
            storage_estimation_buffer = pd.Series(
                [float(service_def.storage.override_estimation_buffer)] * len(service_data.index),
                index=service_data.index
            )
        # this is True if 'service_def.min_nodes' is more than what is being suggested
        vm_total_gt = vms_total > vms_suggested
        data_storage_buffer = data_storage * storage_estimation_buffer

        if service_def.storage_scales_with_nodes:
            # in this case total storage = storage * VM number
            data_storage_per_vm = data_storage + data_storage_buffer
            data_storage_total = data_storage_per_vm * vms_total
        elif True in set(vm_total_gt):
            # in this case 'service_def.min_nodes' is more than what is being suggested
            # so we want to add storage buffer and then distribute among all the nodes
            # but only where vm_total_gt = False

            # 1. calculate storage per VM and total for case where ``vms_total <= vms_suggested``
            vm_total_lte = np.invert(vm_total_gt)
            data_storage_per_vm_lt = data_storage / compute['VMs'] * vm_total_lte
            data_storage_total_lt = data_storage_per_vm_lt * vms_total * vm_total_lte

            # 2. calculate storage per VM and total for case where ``vms_total > vms_suggested``
            data_storage_total_gt = (data_storage + data_storage_buffer) * vm_total_gt
            data_storage_per_vm_gt = data_storage_total_gt / vms_total * vm_total_gt

            # combine 1 & 2 and select values according to vm_total_gt
            data_storage_total = data_storage_total_lt + data_storage_total_gt
            data_storage_per_vm = data_storage_per_vm_lt + data_storage_per_vm_gt
        elif not compute['VMs'].any():
            # if this service doesn't have any compute resources
            storage_buffer = data_storage * storage_estimation_buffer
            storage_estimation_buffer = data_storage * estimation_buffer
            data_storage_total = data_storage + storage_buffer + storage_estimation_buffer
        else:
            # data is spread across all VMs
            data_storage_per_vm = data_storage / compute['VMs']
            data_storage_total = data_storage_per_vm * vms_total

        zero = pd.Series([0] * len(vms_suggested), index=vms_suggested.index)
        include_ha_resources = service_def.include_ha_resources
        data_storage_ha = data_storage_total if include_ha_resources else zero.copy()
        data_storage_total = data_storage_total + data_storage_ha

        cores = vms_total * service_def.process.cores_per_node if vms_total.any() else zero.copy()
        cores_ha = cores if include_ha_resources else zero.copy()
        cores_total = cores + cores_ha

        ram = vms_total * service_def.process.ram_per_node if vms_total.any() else zero.copy()
        ram_ha = ram if include_ha_resources else zero.copy()
        ram_total = ram + ram_ha

        vms_ha = vms_total.copy() if include_ha_resources else zero.copy()
        vms_total = vms_total + vms_ha

        os_storage = vms_total * config.vm_os_storage_gb * (1000.0 ** 3)
        os_storage_ha = vms_ha * config.vm_os_storage_gb * (1000.0 ** 3)
        data = OrderedDict([
            # ('Cores Per VM', service_def.process.cores_per_node),
            # ('Cores HA', cores_ha),
            ('Cores Total', cores_total),
            # ('RAM Per VM', service_def.process.ram_per_node),
            # ('RAM HA (GB)', ram_ha),
            ('RAM Total (GB)', ram_total),
            # ('Data Storage Per VM (GB)', tenth_round(to_gb((data_storage_per_vm) if compute['VMs'].any() else zero.copy()))),
            # ('Data Storage HA (%s)' % storage_units, tenth_round(to_display((data_storage_ha).map(np.ceil)))),
            ('Data Storage Total (%s)' % storage_units, tenth_round(to_display((data_storage_total).map(np.ceil)))),
            ('Data Storage RAW (includes HA) (%s)' % storage_units, to_display(data_storage + data_storage_ha)),
            ('VMs HA', vms_ha),
            ('VMs Total', vms_total),
            ('VM Buffer', node_buffer),
            # ('Buffer %', estimation_buffer),
            # ('OS Storage HA (GB)', (to_gb(os_storage_ha)).map(np.ceil)),
            ('OS Storage Total (Bytes)', os_storage),
            ('OS Storage Total (GB)', (to_gb(os_storage)).map(np.ceil)),
            ('Storage Group', service_def.storage.group),
        ])
        combined = pd.DataFrame(data=data)
        summary_df[service_name] = combined

    return pd.Panel(summary_df)  # toto: use multiindex dataframe


def compare_summaries(config, summaries_by_date):
    data_storage_series = []
    storage_by_group_series = []
    compute_series = []
    dates = sorted(list(summaries_by_date))
    storage_units = config.storage_display_unit
    for date in dates:
        summary_data = summaries_by_date[date]
        data_storage_series.append(summary_data.service_summary['Data Storage Total (%s)' % storage_units])
        storage_by_group_series.append(summary_data.storage_by_group)
        compute = summary_data.service_summary[['Cores Total', 'RAM Total (GB)', 'VMs Total']]
        compute = compute.rename({'Cores Total': 'Cores', 'RAM Total (GB)': 'RAM (GB)', 'VMs Total': 'VMs'}, axis=1)
        compute_series.append(compute)

    first_date = list(summaries_by_date)[0]
    group_series = summaries_by_date[first_date].service_summary['Storage Group']
    data_storage_series.append(group_series)

    keys = [format_date(date) for date in dates]

    storage_by_cat = pd.concat(data_storage_series, axis=1, keys=keys + ['Group'])
    storage_by_cat = storage_by_cat[storage_by_cat != 0.0].dropna(how='all')
    storage_by_cat = storage_by_cat.drop('Total')

    storage_by_group = pd.concat(storage_by_group_series, axis=1, keys=keys)

    compute = pd.concat(compute_series, axis=1, keys=keys)
    compute = compute[compute > 0].dropna()
    return SummaryComparison(storage_by_cat, storage_by_group, compute)

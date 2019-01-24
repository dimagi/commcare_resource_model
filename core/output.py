from core.utils import format_date
import pandas as pd
import numpy as np

COMPARISONS_SHEET = 'Comparisons'
SUMMARY_SHEET = '%s - %s users'
SUMMARY_SHEET_ANALYSIS = '%s (%s) - %s'

STORAGE_GROUP_INDEX = 'Storage Group'
STORAGE_CAT_INDEX = 'Service'
SERVICE_INDEX = 'Service'


def write_summary_comparisons(config, writer, user_counts, comparisons, prefix=''):
    storage_by_cat, storage_by_group, compute = comparisons
    sheet = '%s%s' % (prefix, COMPARISONS_SHEET)

    user_count_table = [
        (format_date(date), count)
        for date, count in sorted(user_counts.items(), key=lambda k: k[0])
    ]
    writer.write_user_counts_horizontal(sheet, user_count_table)

    storage_group_header = '%sStorage by Group (%s)' % (prefix, config.storage_display_unit)
    writer.write_data_frame(storage_by_group, sheet, STORAGE_GROUP_INDEX, storage_group_header)

    categories = compute.columns.levels[1]
    totals = pd.concat([compute.xs(category, axis=1, level=1).loc['Total'] for category in categories], keys=categories).unstack()
    writer.write_data_frame(totals, sheet, 'Compute Resource', '%sCompute Totals' % prefix)

    storage_cat_header = '%sStorage by Service (%s)' % (prefix, config.storage_display_unit)
    writer.write_data_frame(storage_by_cat, sheet, STORAGE_CAT_INDEX, storage_cat_header)

    for category in categories:
        comparison_header = '%s%s' % (prefix, category)
        writer.write_data_frame(compute.xs(category, axis=1, level=1), sheet, SERVICE_INDEX, comparison_header, has_total_row=True)
    writer.write_data_frame(compute, sheet, SERVICE_INDEX, '%sCompute Combined' % prefix, has_total_row=True)


def write_summary_data(config, writer, summary_date, summary_data, user_count, field_to_modify, subfield_to_modify, step_value):
    # sheet_name = SUMMARY_SHEET % (format_date(summary_date), short_user_count(user_count))
    sheet_name = SUMMARY_SHEET_ANALYSIS  % (field_to_modify, subfield_to_modify, step_value)
    writer.write_user_counts_vertical(sheet_name, [(format_date(summary_date), user_count)])

    storage_group_header = 'Storage by Group (%s)' % config.storage_display_unit
    writer.write_data_frame(
        summary_data.storage_by_group,
        sheet_name,
        STORAGE_GROUP_INDEX,
        storage_group_header
    )

    columns = (
        'Cores Per VM', 'RAM Per VM', 'Data Storage Per VM (GB)',
        'VMs Total', 'Data Storage Total (TB)',
        'Storage Group', 'OS Storage Total (GB)'
    )
    vm_summary = summary_data.service_summary.loc[:, columns]
    vm_summary.loc[:,'OS Storage Per VM (GB)'] = pd.Series([config.vm_os_storage_gb] * len(vm_summary), index=vm_summary.index)
    vm_summary = vm_summary.drop('Total', axis=0).replace(0, np.NaN)
    writer.write_data_frame(vm_summary, sheet_name, 'Service', 'VM Summary')
    writer.write_data_frame(
        summary_data.service_summary.replace(0, np.NaN),
        sheet_name,
        'Service',
        'Service Detailed Summary',
        has_total_row=True
    )


def write_raw_service_data(writer, service_data, summary_data, title):
    sections = list(sorted({d[0] for d in service_data}))
    for section in sections:
        sdata = service_data[section]
        sdata.columns = sdata.columns.get_level_values(1)
        combined = sdata.join(summary_data[section])
        writer.write_data_frame(combined, "{} ({})".format(title, section), 'Dates')

def write_raw_data(writer, usage, title):
        writer.write_data_frame(usage, title, 'Dates')


def short_user_count(count):
    return '%sK' % int(count / 1000)

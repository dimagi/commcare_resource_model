import argparse
import subprocess
from collections import namedtuple

import pandas as pd

from core.config import config_from_path
from core.generate import generate_usage_data, generate_service_data
from core.output import write_raw_data, write_summary_comparisons, write_summary_data, write_raw_service_data
from core.summarize import incremental_summaries, \
    summarize_service_data, compare_summaries, get_summary_data
from core.writers import ConsoleWriter
from core.writers import ExcelWriter

SummaryData = namedtuple('SummaryData', 'storage compute')


def get_git_revision_hash():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip().decode('utf8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser('CommCare Cluster Model')
    parser.add_argument('config', help='Path to config file')
    parser.add_argument('-o', '--output', help='Write output to Excel file at this path.')
    parser.add_argument('-s', '--service', help='Only output data for specific service.')

    args = parser.parse_args()

    pd.options.display.float_format = '{:.1f}'.format

    config = config_from_path(args.config)
    usage = generate_usage_data(config)
    if args.service:
        config.services = {
            args.service: config.services[args.service]
        }

    service_data = generate_service_data(config, usage)

    if config.summary_dates:
        summary_dates = config.summary_date_vals
    else:
        summary_dates = [usage.iloc[-1].name]  # summarize at final date

    is_excel = bool(args.output)
    if is_excel:
        writer = ExcelWriter(args.output)
    else:
        writer = ConsoleWriter()

    with writer:
        summaries = {}
        user_count = {}
        date_list = list(usage.index.to_series())
        summary_data = get_summary_data(config, service_data)
        for date in summary_dates:
            summaries[date] = summarize_service_data(config, summary_data, date)
            user_count[date] = usage.loc[date]['users']

        if len(summary_dates) == 1:
            date = summary_dates[0]
            summary_data_snapshot = summaries[date]
            write_summary_data(config, writer, date, summary_data_snapshot, user_count[date])

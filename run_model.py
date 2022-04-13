import argparse
import itertools
import os
import subprocess
import sys
from collections import namedtuple, OrderedDict

import pandas as pd

from core.config import config_from_path
from core.generate import generate_usage_data, generate_service_data
from core.output import write_raw_data, write_summary_comparisons, write_summary_data, write_raw_service_data
from core.summarize import incremental_summaries, \
    summarize_service_data, compare_summaries, get_summary_data
from core.utils import apply_context, context_pattern
from core.writers import ConsoleWriter
from core.writers import ExcelWriter

SummaryData = namedtuple('SummaryData', 'storage compute')


def get_git_revision_hash():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip().decode('utf8')


def get_combined_sets(sets):
    combined_sets = []
    for combinations in list(itertools.product(*sets.values())):
        context = {}
        name = None
        for item in combinations:
            item = item.copy()
            item_name = item.pop('name', None)
            context.update(item)
            if item_name:
                if not name:
                    name = item_name
                else:
                    name += f'-{item_name}'
        context['name'] = name
        for key, val in context.items():
            if key != 'name' and isinstance(val, str):
                context[key] = eval(val, None, context)

        combined_sets.append(context)
    return combined_sets


if __name__ == '__main__':
    parser = argparse.ArgumentParser('CommCare Cluster Model')
    parser.add_argument('config', help='Path to config file')
    parser.add_argument('-o', '--output', help='Write output to Excel file at this path.')
    parser.add_argument('-s', '--service', help='Only output data for specific service.')
    parser.add_argument('-u', '--usage', help='Print a specific usage field.')
    parser.add_argument('--set', help='Only run a specific set.')

    args = parser.parse_args()

    pd.options.display.float_format = '{:.1f}'.format

    config_path = args.config
    config_name = os.path.basename(config_path)
    config = config_from_path(config_path)

    if args.service:
        config.services = {
            args.service: config.services[args.service]
        }

    combined_sets = get_combined_sets(config.sets) if config.sets else [{'name': 'default'}]

    if args.set:
        combined_sets = [s for s in combined_sets if s['name'] == args.set]

    multiple_sets = len(combined_sets) > 1
    is_excel = bool(args.output)
    if multiple_sets and is_excel:
        placeholders = context_pattern.findall(args.output)
        if '{name}' not in placeholders:
            print("Add '{name}' placeholder to the output filename create unique files per set.")
            sys.exit(1)

    sets_snapshots = OrderedDict()
    for set_context in combined_sets:

        print(f"Generating data for set '{set_context['name']}'")
        usage = generate_usage_data(config, set_context)

        if args.usage:
            print(usage[args.usage])

        service_data = generate_service_data(config, usage)

        if config.summary_dates:
            summary_dates = config.summary_date_vals
        else:
            summary_dates = [usage.iloc[-1].name]  # summarize at final date

        summary_dates = sorted(summary_dates)

        if is_excel:
            output_path = apply_context(set_context, args.output)
            print(f'Writing output to "{output_path}"')
            writer = ExcelWriter(output_path)
        else:
            writer = ConsoleWriter()

        with writer:
            summaries = OrderedDict()
            user_count = {}
            date_list = list(usage.index.to_series())
            summary_data = get_summary_data(config, service_data)
            for date in summary_dates:
                summaries[date] = summarize_service_data(config, summary_data, date)
                user_count[date] = usage.loc[date]['users']

            if multiple_sets and config.sets_summary_date_val:
                sets_snapshots[set_context['name']] = summaries[config.sets_summary_date_val]

            if len(summary_dates) == 1:
                date = summary_dates[0]
                summary_data_snapshot = summaries[date]
                write_summary_data(config, writer, date, summary_data_snapshot, user_count[date])
            else:
                summary_comparisons = compare_summaries(config, summaries)
                incrementals = incremental_summaries(summary_comparisons, summary_dates)
                write_summary_comparisons(config, writer, user_count, summary_comparisons)
                write_summary_comparisons(config, writer, user_count, incrementals, prefix='Incremental ')

                for date in sorted(summaries):
                    write_summary_data(config, writer, date, summaries[date], user_count[date])

            if is_excel:
                # only write raw data if writing to Excel
                write_raw_data(writer, usage, 'Usage')
                write_raw_service_data(writer, service_data, summary_data, 'Raw Data')

                with open(config_path, 'r') as f:
                    config_string = 'Config filename: {}\nGit commit: {}\n\n{}'.format(
                        config_name,
                        get_git_revision_hash(),
                        f.read()
                    )
                    writer.write_config_string(config_string)

    if sets_snapshots and args.output:
        output_path = apply_context({'name': 'comparison'}, args.output)
        print(f'Writing comparison output to "{output_path}"')
        set_comparisons = compare_summaries(config, sets_snapshots)
        comparison_writer = ExcelWriter(output_path)
        with comparison_writer:
            write_summary_comparisons(config, comparison_writer, {}, set_comparisons)

import numpy as np
import pandas as pd

from core.models import models_by_slug
from core.utils import byte_map


def generate_usage_data(config):
    model_classes = models_by_slug()

    models = [
        model_classes[model_def.model](name, **model_def.model_params)
        for name, model_def in config.usage.items()
    ]
    usage_df = pd.DataFrame()
    while models:
        models_len = len(models)
        for model in models:
            if model.can_run(usage_df):
                models.remove(model)
                usage_df = pd.concat([usage_df, model.data_frame(usage_df)], axis=1)
        if len(models) == models_len:
            # no models could run which means we're stuck
            models_remaining = [model.name for model in models]
            raise Exception('Unmet dependencies for models: %s' % ', '.join(models_remaining))

    return usage_df


def generate_service_data(config, usage_data):
    dfs = []
    users = usage_data['users']
    for service_name, service_def in config.services.items():
        data_storage = _service_storage_data(config, service_def, usage_data)
        compute = ComputeModel(service_name, service_def).data_frame(usage_data, data_storage)
        data = pd.concat([users, compute, data_storage], keys=['Users', 'Compute', 'Data Storage'], axis=1)
        dfs.append(data)
    return pd.concat(dfs, keys=list(config.services), axis=1)


def _service_storage_data(config, service_def, usage_data):
    def _to_df(storage, raw=None):
        df = pd.DataFrame({
            'storage': storage,
        })
        if raw is not None:
            return pd.concat([df, raw], axis=1)
        else:
            return df

    if service_def.storage.data_models:
        data_storage = _service_data_size(
            service_def.storage.data_models,
            service_def.storage.static_baseline_bytes,
            usage_data,
            service_def.storage.redundancy_factor
        )
        buffer = config.storage_buffer
        if service_def.storage.override_storage_buffer != None:
            buffer = service_def.storage.override_storage_buffer
        total = data_storage.sum(axis=1) * float(1 + buffer)
        return _to_df(total, data_storage)
    else:
        static = service_def.storage.static_baseline_bytes * service_def.storage.redundancy_factor
        data_storage = pd.Series([static] * len(usage_data), index=usage_data.index)
        return _to_df(data_storage)


def _service_data_size(data_models, static_baseline_bytes, usage_data, redundancy_factor=1):
    def _service_requirement(size_def):
        bytes = usage_data[size_def.referenced_field] * size_def.unit_bytes
        return bytes * redundancy_factor

    baseline = pd.Series(
        [static_baseline_bytes * redundancy_factor] * len(usage_data),
        index=usage_data.index, name='static_baseline'
    )
    return pd.concat([_service_requirement(model) for model in data_models] + [baseline], axis=1)


class ComputeModel(object):
    def __init__(self, service_name, service_def):
        self.service_name = service_name
        self.service_def = service_def

    def _get_process_series(self, process_def, usage_data):
        if process_def.static_number:
            return pd.Series([process_def.static_number] * len(usage_data), index=usage_data.index)
        else:
            return (usage_data / float(process_def.capacity)).map(np.ceil)

    def data_frame(self, current_data_frame, data_storage):
        usage = current_data_frame[self.service_def.usage_field]
        if self.service_def.process.sub_processes:
            processes = pd.concat([
                self._get_process_series(sub_process, usage)
                for sub_process in self.service_def.process.sub_processes
            ], keys=[p.name for p in self.service_def.process.sub_processes], axis=1)

            total = processes.apply(sum, axis=1)
            cores = total * float(self.service_def.process.cores_per_sub_process)
            ram = total * float(self.service_def.process.ram_per_sub_process)
            vms_by_cores = cores / self.service_def.process.cores_per_node
            vms_by_ram = ram / self.service_def.process.ram_per_node
            vms = vms_by_cores if vms_by_cores[-1] > vms_by_ram[-1] else vms_by_ram
            compute = pd.concat([cores, ram, vms.map(np.ceil)], keys=['CPU', 'RAM', 'VMs'], axis=1)
        elif self.service_def.usage_capacity_per_node:
            nodes = (usage / self.service_def.usage_capacity_per_node).map(np.ceil)
            compute = pd.concat([
                nodes * self.service_def.process.cores_per_node,
                nodes * self.service_def.process.ram_per_node,
                nodes
            ], keys=['CPU', 'RAM', 'VMs'], axis=1)
        else:
            nodes = pd.Series([self.service_def.static_number] * len(usage), index=usage.index)
            compute = pd.concat([nodes, nodes, nodes], keys=['CPU', 'RAM', 'VMs'], axis=1)

        compute['VMs Usage'] = compute['VMs']
        if self.service_def.max_storage_per_node_bytes:
            # Add extra VMs to keep storage per VM within range
            max_supported = compute['VMs'] * self.service_def.max_storage_per_node_bytes
            extra = data_storage['storage'] - max_supported
            extra[extra < 0] = 0
            extra_vms = np.ceil(extra / self.service_def.max_storage_per_node_bytes)
            compute['VMs'] = compute['VMs'] + extra_vms
            compute['Additional VMs (storage)'] = extra_vms

        if self.service_def.process.ram_model:
            # Add extra VMs if we need more RAM
            ram_requirement = _service_data_size(
                self.service_def.process.ram_model,
                0,
                current_data_frame,
                self.service_def.process.ram_redundancy_factor,
            ).sum(axis=1)
            ram_requirement = ram_requirement / byte_map['GB']
            ram_per_node_excl_baseline = self.service_def.process.ram_per_node - self.service_def.process.ram_static_baseline
            current_allocation = compute['VMs'] * ram_per_node_excl_baseline
            difference = ram_requirement - current_allocation

            difference[difference < 0] = 0
            extra_vms = np.ceil(difference / ram_per_node_excl_baseline)
            compute['VMs'] = compute['VMs'] + extra_vms
            compute['Additional VMs (RAM)'] = extra_vms
            compute['RAM requirement'] = ram_requirement

        return compute

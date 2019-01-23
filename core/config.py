import jsonobject
import yaml
from datetime import datetime
from jsonobject.base import get_dynamic_properties

from core.utils import storage_display_to_bytes


class UsageModelDef(jsonobject.JsonObject):
    _allow_dynamic_properties = True
    model = jsonobject.StringProperty(required=True)

    @property
    def model_params(self):
        return get_dynamic_properties(self)


class StorageSizeDef(jsonobject.JsonObject):
    _allow_dynamic_properties = False
    referenced_field = jsonobject.StringProperty(required=True)
    unit_size = jsonobject.DefaultProperty(required=True)

    @property
    def unit_bytes(self):
        return storage_display_to_bytes(str(self.unit_size))


class SubProcessDef(jsonobject.JsonObject):
    """
    name: Name of the process
    static_number: Assume a fixed number of processes
    usage_field: Field to reference for capacity. Defaults to 'users'
    capacity: Usage capacity that each process can support. e.g. 500 users per process

    Only one of ``static_number`` and ``capacity`` should be supplied.
    """
    name = jsonobject.StringProperty()
    static_number = jsonobject.IntegerProperty()
    capacity = jsonobject.IntegerProperty()

    def validate(self, required=True):
        if self.static_number:
            assert not self.capacity, 'only one of static_number and capacity should be provided'
        else:
            assert self.capacity, 'one of static_number or capacity required'


class StorageDef(jsonobject.JsonObject):
    _allow_dynamic_properties = False
    group = jsonobject.StringProperty()
    redundancy_factor = jsonobject.IntegerProperty(default=1)
    static_baseline = jsonobject.DefaultProperty(default=0)
    data_models = jsonobject.ListProperty(StorageSizeDef)
    override_storage_buffer = jsonobject.DecimalProperty()
    override_estimation_buffer = jsonobject.DecimalProperty()

    @property
    def static_baseline_bytes(self):
        return storage_display_to_bytes(str(self.static_baseline))


class ProcessDef(jsonobject.JsonObject):
    _allow_dynamic_properties = False
    cores_per_node = jsonobject.IntegerProperty()

    # TODO: could refactor this into different process configs for different types of processes
    ram_per_node = jsonobject.IntegerProperty()
    ram_static_baseline = jsonobject.DefaultProperty(default=0)  # per node
    ram_model = jsonobject.ListProperty(StorageSizeDef)
    ram_redundancy_factor = jsonobject.IntegerProperty(default=1)

    cores_per_sub_process = jsonobject.DecimalProperty()
    ram_per_sub_process = jsonobject.DecimalProperty()
    sub_processes = jsonobject.ListProperty(SubProcessDef)

    def validate(self, required=True):
        if self.processes:
            assert self.cores_per_sub_process, 'cores_per_sub_process required if more than one process listed'
            assert self.ram_per_sub_process, 'ram_per_sub_process required if more than one process listed'


class ServiceDef(jsonobject.JsonObject):
    _allow_dynamic_properties = False
    static_number = jsonobject.IntegerProperty(default=0)
    usage_capacity_per_node = jsonobject.IntegerProperty()
    usage_field = jsonobject.StringProperty(default='users')
    storage_scales_with_nodes = jsonobject.BooleanProperty(default=False)
    max_storage_per_node = jsonobject.DefaultProperty()
    min_nodes = jsonobject.IntegerProperty(default=0)
    include_ha_resources = jsonobject.BooleanProperty(default=False)
    storage = jsonobject.ObjectProperty(StorageDef)
    process = jsonobject.ObjectProperty(ProcessDef)

    def validate(self, required=True):
        super(ServiceDef, self).validate(required=required)
        if not self.usage_capacity_per_node:
            assert self.process.sub_processes, 'Service is missing capacity configuration'
        if self.max_storage_per_node:
            assert not self.storage_scales_with_nodes, 'max_storage_per_node not compatible ' \
                                                       'with "storage_scales_with_nodes"'

    @property
    def max_storage_per_node_bytes(self):
        if not self.max_storage_per_node:
            return 0
        return storage_display_to_bytes(str(self.max_storage_per_node))


class ClusterConfig(jsonobject.JsonObject):
    estimation_buffer = jsonobject.DecimalProperty(required=True)
    estimation_growth_factor = jsonobject.DecimalProperty(default=0)
    storage_buffer = jsonobject.DecimalProperty(required=True)
    storage_display_unit = jsonobject.StringProperty(default='GB')
    summary_dates = jsonobject.ListProperty()
    vm_os_storage_gb = jsonobject.IntegerProperty(required=True)
    vm_os_storage_group = jsonobject.StringProperty(required=True)

    usage = jsonobject.DictProperty(UsageModelDef)
    services = jsonobject.DictProperty(ServiceDef)

    def validate(self, required=True):
        super(ClusterConfig, self).validate(required=required)
        self.summary_date_vals

    @property
    def summary_date_vals(self):
        return [
            datetime.strptime(date, "%Y-%m")
            for date in self.summary_dates
        ]


def cluster_config_from_path(config_path):
    with open(config_path, 'r') as f:
        return ClusterConfig(yaml.load(f))

def dict_config_from_path(config_path):
    with open(config_path, 'r') as f:
        return yaml.load(f)

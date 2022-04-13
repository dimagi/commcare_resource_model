import logging
from abc import ABC, abstractmethod
from collections import namedtuple

import pandas as pd

from core.utils import apply_context

logger = logging.getLogger(__name__)

DateRange = namedtuple('DateRange', 'start, end')


def models_by_slug():
    df_models = [
        DateValueModel,
        CumulativeModel,
        LimitedLifetimeModel,
        DerivedSum,
        DerivedProduct,
        DerivedFactor,
        InvertDerivedFactor,
        BaselineWithGrowth,
    ]

    return {
        model.slug: model for model in df_models
    }


class DFModel(ABC):
    @property
    @abstractmethod
    def slug(self):
        raise NotImplemented

    @abstractmethod
    def data_frame(self, current_data_frame):
        raise NotImplemented

    @property
    def dependant_fields(self):
        return []

    def can_run(self, current_data_frame):
        if not self.dependant_fields:
            return True

        columns = set(current_data_frame.columns)
        return not bool(set(self.dependant_fields) - columns)


class DateValueModel(DFModel):
    slug = 'date_range_value'

    def __init__(self, context, name, ranges):
        self.context = context
        self.name = name
        self.ranges = [
            [apply_context(context, item, int) for item in range_]
            for range_ in ranges
        ]

    def data_frame(self, current_data_frame):

        def get_dataframe_for_range(range_):
            if len(range_) == 2:
                index = pd.DatetimeIndex([range_[0]], freq='MS')
                return pd.DataFrame({self.name: [range_[1]]}, index=index)
            elif len(range_) == 3:
                return pd.DataFrame({self.name: range_[2]}, index=pd.date_range(range_[0], range_[1], freq='MS'))

        df = pd.concat([
            get_dataframe_for_range(range_)
            for range_ in self.ranges]
        )
        if len(current_data_frame.index) and len(df.index) != len(current_data_frame.index):
            logger.warning(f"[WARNING] Dataframe for '{self.name}' has different index")
        return df


class CumulativeModel(DFModel):
    """Items that accumulate over time.
    For example form submissions."""
    slug = 'cumulative'

    def __init__(self, context, name, dependant_field, start_with=0):
        self.context = context
        self.name = name
        self.dependant_field = dependant_field
        self.start_with = apply_context(context, start_with, int)

    @property
    def dependant_fields(self):
        return [self.dependant_field]

    def data_frame(self, current_data_frame):
        monthly_data = current_data_frame[self.dependant_field]
        return _get_cumulative_data(self.name, monthly_data, self.start_with)


def _get_cumulative_data(name, monthly_data, start_with=0):
    monthly_data = monthly_data.copy()
    monthly_data[0] += start_with
    cumulative = monthly_data.cumsum()
    cumulative.name = name
    return pd.DataFrame([cumulative]).T


class LimitedLifetimeModel(CumulativeModel):
    """Extends the cumulative model by giving items a finite lifespan"""
    slug = 'cumulative_limited_lifespan'

    def __init__(self, context, name, dependant_field, lifespan, start_with=0):
        super(LimitedLifetimeModel, self).__init__(context, name, dependant_field, start_with=start_with)
        self.lifespan = lifespan

    def data_frame(self, current_data_frame):
        cum_data = super(LimitedLifetimeModel, self).data_frame(current_data_frame)
        live_items = cum_data - cum_data.shift(self.lifespan)
        live_items = live_items.fillna(cum_data[0:self.lifespan])
        live_items.name = self.name
        return live_items.astype(int)


class DerivedModel(DFModel):
    """Base class for models that are derived from other fields"""
    @property
    @abstractmethod
    def func(self):
        raise NotImplemented

    def __init__(self, context, name, dependant_fields, start_with=None):
        self.context = context
        self.name = name
        self._dependant_fields = dependant_fields
        self.start_with = apply_context(context, start_with, int)

    @property
    def dependant_fields(self):
        return self._dependant_fields

    def data_frame(self, current_data_frame):
        fields = self.dependant_fields
        if len(fields) == 1:
            fields = fields[0]
        series = current_data_frame[fields].apply(self.func, axis=1)
        series.name = self.name
        if self.start_with:
            series[0] += self.start_with
        return pd.DataFrame([series]).T


class DerivedSum(DerivedModel):
    """Sum multiple fields"""
    slug = 'derived_sum'
    func = sum


class DerivedProduct(DerivedModel):
    """Multiply multiple fields"""
    slug = 'product'

    @property
    def func(self):
        def _prod(fields):
            return fields.product()

        return _prod


class DerivedFactor(DerivedModel):
    """Multiply a single other field by a static factor"""
    slug = 'derived_factor'

    def __init__(self, context, name, dependant_field, factor, start_with=0):
        super(DerivedFactor, self).__init__(context, name, [dependant_field], start_with)
        self.factor = apply_context(context, factor, float)

    @property
    def func(self):
        def _mul(val, **kwargs):
            return val * self.factor

        return _mul


class InvertDerivedFactor(DerivedModel):
    """Multiply a single other field by a static factor"""
    slug = 'invert_derived_factor'

    def __init__(self, context, name, dependant_field, factor, start_with=0):
        super(InvertDerivedFactor, self).__init__(context, name, [dependant_field], start_with)
        self.factor = apply_context(context, factor, float)

    @property
    def func(self):
        def _div(val, **kwargs):
            return val / self.factor

        return _div


class BaselineWithGrowth(DFModel):
    """Used to model something with a starting value that grows over time
    e.g. cases per user: 1000 baseline + 50 cases per month
    """
    slug = 'baseline_with_growth'

    def __init__(self, context, name, dependant_field, baseline, monthly_growth, start_with=0):
        """
        :param name:
        :param dependant_field: Field to apply baseline and monthly growth against
        :param baseline: Number of items at start
        :param monthly_growth: Number of new items per month
        :param start_with:  Int used to account for existing data
        """
        self.context = context
        self.name = name
        self.dependant_field = dependant_field
        self.baseline = baseline
        self.monthly_growth = monthly_growth
        self.start_with = start_with

    @property
    def dependant_fields(self):
        return [self.dependant_field]

    def data_frame(self, current_data_frame):
        baseline_name = '{}_baseline'.format(self.name)
        baseline_model = DerivedFactor(self.context, baseline_name, self.dependant_field, self.baseline)
        baseline = baseline_model.data_frame(current_data_frame)[baseline_name]

        monthly_name = '{}_monthly'.format(self.name)
        monthly_model = DerivedFactor(self.context, monthly_name, self.dependant_field, self.monthly_growth)
        monthly = monthly_model.data_frame(current_data_frame)[monthly_name]

        cumulative_monthly = _get_cumulative_data('cumulative'.format(self.name), monthly, self.start_with)

        total = baseline + cumulative_monthly['cumulative']
        total.name = self.name

        return pd.DataFrame([baseline, monthly, total]).T

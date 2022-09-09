import numpy as np
import pandas as pd
from copy import copy
from typing import Union, List, Tuple, Optional, Iterable
from pyhts import _accuracy

__all__ = ["Hierarchy"]


class Hierarchy:
    """Class for a hierarchy structure.

    **Attributes**

        .. py:attribute:: s_mat

            summing matrix.
        .. py:attribute:: period

            frequency of time series.
        .. py:attribute:: node_name

            name of each node in the pattern: level-name_attribute-anme
        .. py:attribute:: node_level

            level name of each node.
    """

    def __init__(self, s_mat, node_level, names, period, level_name=None):
        self.s_mat = s_mat.astype('int8')
        """ Summing matrix. """
        self.node_level = np.array(node_level)
        self.level_name = np.array(level_name)
        self.node_name = np.array(names)
        self.period = period

    @classmethod
    def new(cls, df: pd.DataFrame,
            structures: List[Tuple[str, ...]],
            excludes: List[Tuple[str, ...]] = None,
            includes: List[Tuple[str, ...]] = None,
            period: int = 1) -> "Hierarchy":
        """Construct hierarchy from data table that each row represents a unique bottom level time series.
        This method is suitable for complex hierarchical structure.

        **Examples**

            >>> from pyhts import Hierarchy
            >>> df = pd.DataFrame({"City": ["A", "A", "B", "B"], "Store": ["Store1", "Store2", "Store3", "Store4"]})
            >>> hierarchy = Hierarchy.new(df, [("City", "Store")])
            >>> hierarchy.node_name
            array(['total_total', 'City_A', 'City_B', 'Store_Store1', 'Store_Store2',
                   'Store_Store3', 'Store_Store4'], dtype=object)
            >>> hierarchy.s_mat
            array([[1, 1, 1, 1],
                   [1, 1, 0, 0],
                   [0, 0, 1, 1],
                   [1, 0, 0, 0],
                   [0, 1, 0, 0],
                   [0, 0, 1, 0],
                   [0, 0, 0, 1]], dtype=int8)
            >>> df = pd.DataFrame({"City": ["A", "A", "B", "B"], "Category": ["C1", "C2", "C1", "C2"]})
            >>> hierarchy = Hierarchy.new(df, [("City",), ("Category",)])
            >>> hierarchy.s_mat
            array([[1, 1, 1, 1],
                   [1, 1, 0, 0],
                   [0, 0, 1, 1],
                   [1, 0, 1, 0],
                   [0, 1, 0, 1],
                   [1, 0, 0, 0],
                   [0, 1, 0, 0],
                   [0, 0, 1, 0],
                   [0, 0, 0, 1]], dtype=int8)

        :param df: DataFrame contains keys for determining hierarchical structural.
        :param structures: The structure of the hierarchy. It should be a list, where each element represents the \
        hierarchical structure of one natural hierarchy. \
        The element should be tuple of string (column in the dataframe). \
        The order of the columns is top-down. \
        For example, ("category", "sub-category", "item") can be a natural hierarchy.
        :param excludes: middle levels excluded from the hierarchy.
        :param includes: middle levels included in the hierarchy.
        :param period: frequency of the time series, 1 means non-seasonality data, 12 means monthly data.
        :return: Hierarchy object.
        """

        cols = [c for cs in structures for c in cs]
        bottoms = [cs[-1] for cs in structures]

        if len(set(cols)) != len(cols):
            raise ValueError(f"Column should not appear in different tuples (natural hierarchies).")

        levels = []
        for col in cols:
            levels.append({*[col]})
        if len(structures) > 1:
            levels.append({*bottoms})
        if includes:
            for g in includes:
                if {*g} not in levels:
                    levels.insert(-2, {{*[g]}} if isinstance(g, str) else {*g})
        else:
            from itertools import product, combinations
            for j in range(2, len(structures) + 1):
                for comb in combinations(structures, j):
                    for inter in product(*comb):
                        if {*inter} not in levels:
                            levels.insert(-1, {*inter})
            if excludes:
                b_set = set(bottoms)
                for j in excludes:
                    if b_set == set(j):
                        raise ValueError(f"The bottom level {'*'.join(b_set)} can not be excluded!")
                    levels.remove(set(j))

        new_df = copy(df[[list(level)[0] for level in levels if len(level) == 1]])
        for level in levels:
            if len(level) > 1:
                new_df['-'.join(level)] = new_df[list(level)].apply(lambda x: '-'.join(x), axis=1)
        new_df['total'] = 'total'

        level_names = ['total']
        level_names.extend([list(level)[0] for level in levels if len(level) == 1])
        level_names.extend(['-'.join(level) for level in levels if len(level) > 1])
        new_df = new_df[level_names]

        tmp_df = new_df.copy()
        for j, structure in enumerate(structures):
            if len(structure) == 1:
                continue

            for i in range(1, len(structure)):
                foo = new_df.loc[:, structure[i-1:i+1]].drop_duplicates()
                if (foo[structure[i]].value_counts() == 1).all():
                    continue
                else:
                    raise(ValueError(f"Nodes in the level {structure[i]} of {j+1}th hierarchy are not unique."))

        s_dummy = pd.get_dummies(tmp_df)
        s_mat = s_dummy.values.T
        s_mat[-new_df.shape[0]:, :] = np.identity(new_df.shape[0])
        names = list(s_dummy.columns)
        names[-new_df.shape[0]:] = ['-'.join(levels[-1]) + '_' + i for i in list(new_df[level_names[-1]])]

        node_level = [i.split('_')[0] for i in list(s_dummy.columns)]
        return cls(s_mat, pd.Series(node_level), pd.Series(names), period=period, level_name=pd.Series(level_names))

    def aggregate_ts(self, bts: np.ndarray, levels: Optional[Union[str, Iterable[str]]] = None) -> np.ndarray:
        """Aggregate bottom-level time series.

        :param levels: which levels you want. :code:`str` for single level. :code:`Tuple[str, ...]` for interaction of \
        levels.
        :param bts: bottom-level time series
        :return: upper-level time series.
        """
        if isinstance(levels, str):
            assert levels in self.node_level
            s = self.s_mat[np.where(self.node_level == levels)]
            return bts.dot(s.T)
        elif levels is None:
            s = self.s_mat
        else:
            levels = list(levels)
            assert np.isin(levels, self.level_name).all()
            s = self.s_mat[np.isin(self.node_level, levels)]
        return bts.dot(s.T)

    def check_hierarchy(self, *hts):
        for ts in hts:
            if ts.shape[1] == self.s_mat.shape[1]:
                return True
            else:
                return False

    def accuracy_base(self, real, pred, hist=None,
                      levels: Optional[Union[str, Iterable[str]]] = None,
                      measure: List[str] = None) -> pd.DataFrame:
        """Calculate the forecast accuracy of base forecasts.

        :param real: real future observations, array-like of shape (forecast_horizon, m)
        :param pred: forecast values, array-like of shape (forecast_horizon, n)
        :param levels: which levels. None means all levels.
        :param hist: historical time series.
        :param measure: list of measures, e.g., ['mase'], ['mse', 'mase'].
        :return: forecast accuracy of base forecasts.
        """
        assert self.check_hierarchy(real), f"True observations should be of shape (h, m)"
        assert real.shape[0] == pred.shape[0], \
            f" {real.shape} True observations have different lengths with {real.shape} forecasts"

        if measure is None:
            measure = ['mase', 'mape', 'rmse']
        if 'mase' in measure or 'smape' in measure or 'rmsse' in measure:
            assert hist is not None
            assert self.check_hierarchy(hist), "History observations should be of shape(T, m)"
            hist = self.aggregate_ts(hist, levels=levels).T
        else:
            hist = [None] * self.s_mat.shape[0]
        accs = pd.DataFrame()

        agg_true = self.aggregate_ts(real, levels=levels).T

        if levels is not None:
            pred = pred.T[np.isin(self.node_level, levels), ]
        else:
            pred = pred.T

        for me in measure:
            try:
                accs[me] = np.array([getattr(_accuracy, me)(agg_true[i], pred[i], hist[i], self.period)
                                     for i in range(hist.shape[0])])
            except AttributeError:
                print(f'Forecasting measure {me} is not supported!')
        accs.index = self.node_name[np.isin(self.node_level, levels)] if levels is not None else self.node_name
        return accs

    def accuracy(self, real, pred, hist=None,
                 levels: Union[str, None, Iterable[str]] = None,
                 measure: List[str] = None):
        """Calculate the forecast accuracy.

        :param real: real future observations, array-like of shape (forecast_horizon, m)
        :param pred: forecast values, array-like of shape (forecast_horizon, m)
        :param levels: which levels, None means all levels.
        :param hist: historical time series.
        :param measure: list of measures, e.g., ['mase'], ['mse', 'mase'].
        :return: forecast accuracy of reconciled forecasts.
        """
        assert self.check_hierarchy(real), f"True observations should be of shape (h, m)"
        assert self.check_hierarchy(pred), f"Forecast values should be of shape (h, m)"
        assert real.shape[0] == pred.shape[0], \
            f" {real.shape} True observations have different length with {real.shape} forecasts"
        if measure is None:
            measure = ['mase', 'mape', 'rmse']
        if 'mase' in measure or 'smape' in measure or 'rmsse' in measure:
            assert hist is not None
        if hist is not None:
            assert self.check_hierarchy(hist), "History observations should be of shape(T, m)"
            hist = self.aggregate_ts(hist, levels=levels).T
        else:
            hist = [None] * self.s_mat.shape[0]
        agg_true = self.aggregate_ts(real, levels=levels).T
        agg_pred = self.aggregate_ts(pred, levels=levels).T
        accs = pd.DataFrame()
        for me in measure:
            try:
                accs[me] = np.array([getattr(_accuracy, me)(agg_true[i], agg_pred[i], hist[i], self.period)
                            for i in range(agg_true.shape[0])])
            except AttributeError:
                print('This forecasting measure is not supported!')
        accs.index = self.node_name[np.isin(self.node_level, levels)] if levels is not None else self.node_name
        return accs


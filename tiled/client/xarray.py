from collections.abc import Iterable
import builtins
import itertools

import xarray

from ..containers.xarray import (
    DataArrayStructure,
    DatasetStructure,
    VariableStructure,
)

from .array import ClientArrayReader, ClientDaskArrayReader
from .base import BaseArrayClientReader


class ClientDaskVariableReader(BaseArrayClientReader):

    STRUCTURE_TYPE = VariableStructure
    ARRAY_READER = ClientDaskArrayReader

    def __init__(self, *args, route="/variable/block", **kwargs):
        super().__init__(*args, **kwargs)
        self._route = route

    def read_block(self, block, slice=None):
        """
        Read a block (optional sub-sliced) of array data from this Variable.

        Intended for advanced uses. Returns array-like, not Variable.
        """
        structure = self.structure().macro
        return self.ARRAY_READER(
            client=self._client,
            path=self._path,
            metadata=self.metadata,
            params=self._params,
            structure=structure.data,
            route=self._route,
        ).read_block(block, slice)

    def read(self, slice=None):
        structure = self.structure().macro
        array_source = self.ARRAY_READER(
            client=self._client,
            path=self._path,
            metadata=self.metadata,
            params=self._params,
            structure=structure.data,
            route=self._route,
        )
        return xarray.Variable(
            dims=structure.dims, data=array_source.read(slice), attrs=structure.attrs
        )

    def __getitem__(self, slice):
        return self.read(slice)

    # The default object.__iter__ works as expected here, no need to
    # implemented it specifically.

    def __len__(self):
        # As with numpy, len(arr) is the size of the zeroth axis.
        return self.structure().macro.data.macro.shape[0]


class ClientVariableReader(ClientDaskVariableReader):

    ARRAY_READER = ClientArrayReader


class ClientDaskDataArrayReader(BaseArrayClientReader):

    STRUCTURE_TYPE = DataArrayStructure  # used by base class
    VARIABLE_READER = ClientDaskVariableReader  # overriden in subclass

    def __init__(self, *args, route="/data_array/block", **kwargs):
        super().__init__(*args, **kwargs)
        self._route = route

    def read_block(self, block, slice=None):
        """
        Read a block (optional sub-sliced) of array data from this DataArray's Variable.

        Intended for advanced uses. Returns array-like, not Variable.
        """
        structure = self.structure().macro
        variable = structure.variable
        variable_source = self.VARIABLE_READER(
            client=self._client,
            path=self._path,
            metadata=self.metadata,
            params=self._params,
            structure=variable,
            route=self._route,
        )
        return variable_source.read_block(block, slice)

    @property
    def coords(self):
        """
        A dict mapping coord names to Variables.

        Intended for advanced uses. Enables access to read_block(...) on coords.
        """
        structure = self.structure().macro
        result = {}
        for name, variable in structure.coords.items():
            variable_source = self.VARIABLE_READER(
                client=self._client,
                path=self._path,
                metadata=self.metadata,
                params={"coord": name, **self._params},
                structure=variable,
                route=self._route,
            )
            result[name] = variable_source
        return result

    def read(self, slice=None):
        if slice is None:
            slice = ()
        elif isinstance(slice, Iterable):
            slice = tuple(slice)
        else:
            slice = tuple([slice])
        structure = self.structure().macro
        variable = structure.variable
        variable_source = self.VARIABLE_READER(
            client=self._client,
            path=self._path,
            metadata=self.metadata,
            params=self._params,
            structure=variable,
            route=self._route,
        )
        data = variable_source.read(slice)
        coords = {}
        for coord_slice, (name, variable) in itertools.zip_longest(
            slice, structure.coords.items(), fillvalue=builtins.slice(None, None)
        ):
            variable_source = self.VARIABLE_READER(
                client=self._client,
                path=self._path,
                metadata=self.metadata,
                params={"coord": name, **self._params},
                structure=variable,
                route=self._route,
            )
            coords[name] = variable_source.read(coord_slice)
        return xarray.DataArray(data=data, coords=coords, name=structure.name)

    def __getitem__(self, slice):
        return self.read(slice)

    # The default object.__iter__ works as expected here, no need to
    # implemented it specifically.

    def __len__(self):
        # As with numpy, len(arr) is the size of the zeroth axis.
        return self.structure().macro.variable.macro.data.macro.shape[0]


class ClientDataArrayReader(ClientDaskDataArrayReader):

    VARIABLE_READER = ClientVariableReader


class ClientDaskDatasetReader(BaseArrayClientReader):

    STRUCTURE_TYPE = DatasetStructure
    DATA_ARRAY_READER = ClientDaskDataArrayReader
    VARIABLE_READER = ClientDaskVariableReader

    def __init__(self, *args, route="/dataset/block", **kwargs):
        super().__init__(*args, **kwargs)
        self._route = route

    @property
    def data_vars(self):
        structure = self.structure().macro
        return self._build_data_vars(structure)

    @property
    def coords(self):
        structure = self.structure().macro
        return self._build_coords(structure)

    def _build_data_vars(self, structure, columns=None):
        data_vars = {}
        for name, data_array in structure.data_vars.items():
            if (columns is not None) and (name not in columns):
                continue
            data_array_source = self.DATA_ARRAY_READER(
                client=self._client,
                path=self._path,
                metadata=self.metadata,
                params={"variable": name, **self._params},
                structure=data_array,
                route=self._route,
            )
            data_vars[name] = data_array_source
        return data_vars

    def _build_coords(self, structure, columns=None):
        coords = {}
        for name, variable in structure.coords.items():
            if (columns is not None) and (name not in columns):
                continue
            variable_source = self.VARIABLE_READER(
                client=self._client,
                path=self._path,
                metadata=self.metadata,
                params={"variable": name, **self._params},
                structure=variable,
                route=self._route,
            )
            coords[name] = variable_source
        return coords

    def read(self, columns=None):
        structure = self.structure().macro
        data_vars = self._build_data_vars(structure, columns)
        coords = self._build_coords(structure, columns)
        return xarray.Dataset(
            data_vars={k: v.read() for k, v in data_vars.items()},
            coords={k: v.read() for k, v in coords.items()},
            attrs=structure.attrs,
        )

    def __getitem__(self, columns):
        # This is type unstable, matching xarray's behavior.
        if isinstance(columns, str):
            # Return a single column (an xarray.DataArray).
            return self.read(columns=[columns])[columns]
        else:
            # Return an xarray.Dataset with a subset of the available columns.
            return self.read(columns=columns)

    def __iter__(self):
        # This reflects a slight weirdness in xarray, where coordinates can be
        # used in __getitem__ and __contains__, as in `ds[coord_name]` and
        # `coord_name in ds`, but they are not included in the result of
        # `list(ds)`.
        yield from self.structure().macro.data_vars


class ClientDatasetReader(ClientDaskDatasetReader):

    DATA_ARRAY_READER = ClientDataArrayReader
    VARIABLE_READER = ClientVariableReader

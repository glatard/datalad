# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the datalad package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""High-level interface for uninstalling datasets

"""

__docformat__ = 'restructuredtext'

import os
import logging

from os.path import curdir
from os.path import exists
from datalad.support.param import Parameter
from datalad.support.constraints import EnsureStr, EnsureNone
from datalad.distribution.dataset import Dataset, datasetmethod
from datalad.distribution.drop import _drop_files
from datalad.distribution.drop import dataset_argument
from datalad.distribution.drop import check_argument
from datalad.interface.base import Interface
from datalad.interface.base import report_result_objects
from datalad.interface.common_opts import if_dirty_opt
from datalad.interface.common_opts import recursion_flag
from datalad.interface.utils import handle_dirty_datasets
from datalad.interface.utils import path_is_under
from datalad.utils import rmtree


lgr = logging.getLogger('datalad.distribution.uninstall')


def _uninstall_dataset(ds, check, has_super):
    results = []
    if check and ds.is_installed():
        results.extend(_drop_files(ds, curdir, check=True))
    # TODO: uninstall of a subdataset that has a local URL
    #       (e.g. ./anything) implies cannot be undone, decide how, and
    #       if to check for that
    # TODO check that the relevant branched are pushed to a remote
    if ds.get_subdatasets(fulfilled=True):
        raise ValueError('to be uninstalled dataset has present subdatasets, forgot --recursive?')
    # Close any possibly associated process etc with underlying repo.
    # Otherwise - rmtree could fail to remove e.g. under NFS which would
    # still have some files opened by them (thus having .nfs00000xxxx
    # files) forbidding rmdir to work in rmtree
    ds.close()
    if ds.is_installed():
        rmtree(ds.path)
    if has_super and not exists(ds.path):
        # recreate an empty mountpoint to make Git happier
        os.makedirs(ds.path)
    # invalidate loaded ConfigManager:
    ds._cfg = None
    results.append(ds)
    return results


class Uninstall(Interface):
    """Uninstall subdatasets

    This command can be used to uninstall any number of installed subdataset.
    If a to-be-uninstalled subdataset contains presently installed subdatasets
    itself, their recursive removal has to be enabled explicitly to avoid the
    command to exit with an error. This command will error if individual files
    or non-dataset directories are given as input (use the drop or remove
    command depending in the desired goal), nor will it uninstall top-level
    datasets (i.e. datasets that or not a subdataset in another dataset; use
    the remove command for this purpose).

    By default, the availability of at least one remote copy for each currently
    available file in any dataset is verified. As these checks could lead to
    slow operation (network latencies, etc), they can be disabled.

    Any number of paths to process can be given as input. Recursion into
    subdatasets needs to be explicitly enabled, while recursion in
    subdirectories within a dataset as always done automatically. An optional
    recursion limit is applied relative to each given input path.

    Examples
    --------

    Uninstall a subdataset (undo installation)::

      ~/some/dataset$ datalad uninstall somesubdataset1

    """
    _action = 'uninstall'

    _params_ = dict(
        dataset=dataset_argument,
        path=Parameter(
            args=("path",),
            metavar="PATH",
            doc="path/name of the component to be uninstalled",
            nargs="*",
            constraints=EnsureStr() | EnsureNone()),
        recursive=recursion_flag,
        check=check_argument,
        if_dirty=if_dirty_opt,
    )

    @staticmethod
    @datasetmethod(name=_action)
    def __call__(
            path=None,
            dataset=None,
            recursive=False,
            check=True,
            if_dirty='save-before'):

        if dataset and not path:
            # act on the whole dataset if nothing else was specified
            path = dataset.path if isinstance(dataset, Dataset) else dataset
        content_by_ds, unavailable_paths = Interface._prep(
            path=path,
            dataset=dataset,
            recursive=recursive)
        if unavailable_paths:
            lgr.warning('ignored non-installed paths: %s', unavailable_paths)
        # upfront sanity and compliance checks
        if path_is_under(content_by_ds.keys()):
            # behave like `rm` and refuse to remove where we are
            raise ValueError(
                "refusing to uninstall current or parent directory")
        # check that we have no top-level datasets and not files to process
        args_ok = True
        for ds_path in content_by_ds:
            ds = Dataset(ds_path)
            paths = content_by_ds[ds_path]
            if ds_path not in paths:
                lgr.error(
                    "will not act on files at %s (consider the `drop` command)",
                    paths)
                args_ok = False
            if not ds.get_superdataset(
                    datalad_only=False,
                    topmost=False):
                lgr.error(
                    "will not uninstall top-level dataset at %s (consider the `remove` command)",
                    ds.path)
                args_ok = False
        if not args_ok:
            raise ValueError(
                'inappropriate arguments, see previous error message(s)')

        handle_dirty_datasets(
            content_by_ds, mode=if_dirty, base=dataset)

        results = []

        # iterate over all datasets, starting at the bottom
        # to deinit contained submodules first
        for ds_path in sorted(content_by_ds, reverse=True):
            ds = Dataset(ds_path)
            paths = content_by_ds[ds_path]
            results.extend(
                # we confirmed the super dataset presence above
                _uninstall_dataset(ds, check=check, has_super=True))
        # there is nothing to save at the end
        return results

    @classmethod
    def result_renderer_cmdline(cls, res, args):
        report_result_objects(cls, res, args, 'uninstalled')

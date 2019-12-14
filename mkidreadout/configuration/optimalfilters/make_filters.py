import os
import signal
import pickle
import logging
import argparse
import numpy as np
import multiprocessing as mp

import mkidcore.config
import mkidcore.objects  # must be imported for beam map to load from yaml
from mkidcore.pixelflags import filters as flag_dict

import mkidreadout.configuration.optimalfilters.utils as utils

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


class Solution(object):
    """
    Solution class for the filter generation.

    Args:
        config: yaml config object
            The configuration object for the calculation loaded by
            mkidcore.config.load().
        file_names: list of strings
            The file names for the resonator phase snaps.
        save_name: string
            The name to use for saving the file. The prefix will be used for
            saving its output products.
    """
    def __init__(self, config, file_names, save_name=None):
        # input attributes
        self._cfg = config
        self.fallback_template = utils.load_fallback_template(config.filter)
        self.file_names = file_names
        # use None so that config parser can input None in __main__
        self.save_name = "filter_solution.p" if save_name is None else save_name
        # computation attributes
        self.res_ids = np.array([utils.res_id_from_file_name(file_name) for file_name in file_names])
        self.resonators = np.array([Resonator(self.cfg.filter, file_name, self.fallback_template, index=index)
                                    for index, file_name in enumerate(file_names)])
        # output products
        self.filters = {}
        self.flags = {}

    @property
    def cfg(self):
        """The configuration object."""
        return self._cfg

    @cfg.setter
    def cfg(self, config):
        self._cfg = config
        for index, resonator in enumerate(self.resonators):
            # overload resonator configurations
            resonator.cfg = self.cfg.filter
            # overload resonator filter if the configuration filter types don't match
            if self.cfg.filter.filter_type != resonator.cfg.filter_type:
                resonator.result["filter"] = None
                log.debug("Res ID {} filter overloaded".format(self.res_ids[index]))
        log.info("Configuration file updated")

    @classmethod
    def load(cls, file_path):
        """Load in the solution object from a file."""
        with open(file_path, 'rb') as f:
            solution = pickle.load(f)
        solution.save_name = os.path.basename(file_path)
        log.info("Filter solution loaded from {}".format(file_path))
        return solution

    def save(self, file_name=None):
        """Save the solution object to a file."""
        if file_name is None:
            file_name = self.save_name
        file_path = os.path.join(self.cfg.paths.out, file_name)
        with open(file_path, 'wb') as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)
        log.info("Filter solution saved to {}".format(file_path))

    def save_filters(self, file_name=None):
        """Save the filters to a file readable by the firmware."""
        if file_name is None:
            file_name = os.path.splitext(self.save_name)[0] + "_coefficients.txt"
        file_path = os.path.join(self.cfg.paths.out, file_name)
        np.savetxt(file_path, self.filters[self.cfg.filter.filter_type])
        log.info("Filter coefficients saved to {}".format(file_path))

    def process(self, ncpu=1, progress=True):
        """Process all of the files and compute the filters."""
        if ncpu > 1:
            pool = mp.Pool(min(self.cfg.ncpu, mp.cpu_count()), initializer=initialize_worker)
            results = utils.map_async_progress(pool, process_resonator, self.resonators, progress=progress)
            pool.close()
            try:
                # TODO: Python 2.7 bug: hangs on pool.join() with KeyboardInterrupt. The workaround is to use a really
                #  long timeout that hopefully never gets triggered. The 'better' code is:
                #  > pool.join()
                #  > resonators = results.get()
                resonators = results.get(1e5)
                self._add_resonators(resonators)
            except KeyboardInterrupt as error:
                log.error("Keyboard Interrupt encountered: retrieving computed filters before exiting")
                pool.terminate()
                pool.join()
                # TODO: not sure how long it will take to transfer real Resonator objects
                #  (timeout may need to be rethought)
                resonators = results.get(timeout=0.001)
                self._add_resonators(resonators)
                raise error  # propagate error to the main program
        else:
            pbar = utils.setup_progress(self.resonators) if progress and utils.HAS_PB else None
            for index, resonator in enumerate(self.resonators):
                result = process_resonator(resonator)
                self._add_resonators([result])
                if progress and utils.HAS_PB:
                    pbar.update(index)
        self._collect_data()
        self.clear_resonator_data()

    def clear_resonator_data(self):
        """Clear all unnecessary data from the Resonator sub-objects."""
        for resonator in self.resonators:
            resonator.clear_results()

    def plot_summary(self):
        """Plot a summary of the filter computation."""
        pass

    def _add_resonators(self, resonators):
        for resonator in resonators:
            if resonator is not None:
                self.resonators[resonator.index] = resonator

    def _collect_data(self):
        filter_array = np.empty((self.res_ids.size, self.cfg.filter.nfilter))
        for index, resonator in enumerate(self.resonators):
            filter_array[index, :] = resonator.result["filter"]
        self.filters.update({self.cfg.filter.filter_type: filter_array})
        self.flags.update({self.cfg.filter.filter_type: [resonator.result["flag"] for resonator in self.resonators]})


class Resonator(object):
    """
    Class for holding and manipulating a resonator's phase time-stream.

    Args:
        config: yaml config object
            The filter configuration object for the calculation loaded by
            mkidcore.config.load().
        file_name: string
            The file name containing the phase time-stream.
        fallback_template: numpy.ndarray
            A 1D numpy array of size config.ntemplate that will be used for the
            resonator template if it cannot be computed from the phase
            time-stream.
        index: integer (optional)
            An integer used to index the resonator objects. It is not used
            directly by this class.
    """
    def __init__(self, config, file_name, fallback_template, index=None):
        self.index = index
        self.file_name = file_name
        self.cfg = config
        self.fallback_template = fallback_template
        self._time_stream = None

        self._init_results()

        self.pulse_indices = None

    def __getstate__(self):
        self.clear_attributes()
        return self.__dict__

    @property
    def time_stream(self):
        """The phase time-stream of the resonator."""
        if self._time_stream is None:
            # npz = np.load(self.file_name)
            # self._time_stream = npz[npz.keys()[0]]  # TODO: remove
            self._time_stream = np.zeros(int(60e6))
        return self._time_stream

    def clear_attributes(self):
        """Free up memory by removing attributes that can be reloaded from files."""
        self._time_stream = None

    def clear_results(self):
        """Delete computed results from the resonator."""
        # only delete filter since the template isn't stored elsewhere
        self.result["filter"] = None
        # if the filter was flagged reset the flag bitmask
        if self.result["flag"] & flag_dict["bad_filter"]:
            self.result["flag"] = self.result["flag"] ^ flag_dict["bad_filter"]
        if self.result["flag"] & flag_dict["filter_computed"]:
            self.result["flag"] = self.result["flag"] ^ flag_dict["filter_computed"]

    def find_pulse_indices(self):
        """Find the pulse index locations in the time stream."""
        self.pulse_indices = None

    def make_noise(self):
        """Make the noise spectrum for the resonator."""
        if self.result['flag'] & flag_dict['noise_computed']:
            return

        self.result['psd'] = np.zeros(self.cfg.nwindow)
        self.result['flag'] = self.result['flag'] | flag_dict['noise_computed']

    def make_template(self):
        """Make the template for the photon pulse."""
        if self.result['flag'] & flag_dict['template_computed']:
            return
        self._flag_checks(noise=True)

        self.result['template'] = np.zeros(self.cfg.ntemplate)
        self.result['flag'] = self.result['flag'] | flag_dict['template_computed']

    def make_filter(self):
        """Make the filter for the resonator."""
        if self.result['flag'] & flag_dict['filter_computed']:
            return
        self._flag_checks(noise=True, template=True)

        self.result['filter'] = np.zeros(self.cfg.nfilter)
        self.result['flag'] = self.result['flag'] | flag_dict['filter_computed']

    def _init_results(self):
        self.result = {"template": None, "filter": None, "psd": None, "flag": flag_dict["not_started"]}

    def _flag_checks(self, noise=False, template=False):
        if noise:
            assert self.result['flag'] & flag_dict['noise_computed'], "run self.make_noise() first."
        if template:
            assert self.result['flag'] & flag_dict['template_computed'], "run self.make_template first."


def initialize_worker():
    """Initialize multiprocessing.pool worker to ignore keyboard interrupts."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # ignore keyboard interrupt in worker process


def process_resonator(resonator):
    """Process the resonator object and compute it's filter."""
    resonator.find_pulse_indices()
    resonator.make_noise()
    resonator.make_template()
    resonator.make_filter()
    print(resonator.index)
    from time import sleep
    sleep(.01)
    return resonator


def run(config, progress=False, force=False, save_name=None):
    """
    Run the main logic for the filter generation.

    Args:
        config: yaml config object
            The configuration object for the calculation loaded by
            mkidcore.config.load().
        progress: boolean (optional)
            If progressbar is installed and progress=True, a progress bar will
            be displayed showing the progress of the computation.
        force: boolean (optional)
            If force is True, a new solution object will be made. If False and
            'save_name' is a real file, the solution from 'save_name' will be
            loaded in and the computation will be continued from where it left
            off.
        save_name: string (optional)
            If provided, the solution object will be saved with this name.
            Otherwise, a default name will be used. See 'force' for details
            on when the file 'save_name' already exists.
    """
    # set up the Solution object
    if force or (save_name is not None and not os.path.isfile(save_name)):
        log.info("Creating new solution object")
        # get file name list
        # file_names = utils.get_file_list(config.paths.data)  # TODO: remove
        file_names = ["snap_112_resID10000_3212323-2323232.npz" for _ in range(2000)]
        # set up solution file
        sol = Solution(config, file_names, save_name=save_name)
    else:
        log.info("Loading solution object from {}".format(save_name))
        sol = Solution.load(save_name)
        sol.cfg = config

    # get the number of cores to use
    try:
        ncpu = max(1, int(min(config.ncpu, mp.cpu_count())))
    except KeyError:
        ncpu = 1
    log.info("Using {} cores".format(ncpu))

    # make the filters
    try:
        if force or config.filter.filter_type not in sol.filters.keys():
            sol.process(ncpu=ncpu, progress=progress)
            sol.save()
        else:
            log.info("Filter type '{}' has already been computed".format(config.filter.filter_type))
    except KeyboardInterrupt:
        log.error("Keyboard Interrupt encountered: saving the partial solution before exiting")
        sol.save()
        return

    # save the filters
    sol.save_filters()

    # plot summary
    if config.filter.summary_plot:
        sol.plot_summary()


if __name__ == "__main__":
    # make sure the Solution is unpickleable if created from __main__
    from mkidreadout.configuration.optimalfilters.make_filters import Solution

    # parse the command line arguments
    parser = argparse.ArgumentParser(description='Filter Computation Utility')
    parser.add_argument('cfg_file', type=str, help='The configuration file to use for the computation.')
    parser.add_argument('-p', '--progress', action='store_true', dest='progress', help='Enable the progress bar.')
    parser.add_argument('-f', '--force', action='store_true', dest='force',
                        help='Force the recomputation of all of the computation steps.')
    parser.add_argument('-n', '--name', type=str, dest='name',
                        help='The name of the saved solution. The default is used if a name is not supplied.')
    args = parser.parse_args()

    # set up logging
    logging.basicConfig(level="INFO")

    # load the configuration file
    configuration = mkidcore.config.load(args.cfg_file)

    # run the code
    run(configuration, progress=args.progress, force=args.force, save_name=args.name)